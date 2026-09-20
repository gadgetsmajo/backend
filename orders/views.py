from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.core.cache import cache
from django.db import transaction, models
from .models import Order, ServiceRating, Payment, ReturnRequest
from .serializers import OrderSerializer, ServiceRatingSerializer, PaymentSerializer, ReturnRequestSerializer
from .tasks import send_product_rating_notifications
from users.models import Notification
from users.emails import (
    send_admin_new_order_email,
    send_order_confirmed_email,
    send_order_shipped_email,
    send_order_ready_for_pickup_email,
    send_order_delivered_email,
    send_order_cancelled_email,
    send_order_rating_email,
    send_payment_successful_email,
    send_payment_failed_email,
)
import requests as http_requests
import logging

logger = logging.getLogger(__name__)


def _product_image(product) -> str:
    try:
        return product.image.url if product.image else ''
    except Exception:
        return ''


def _notify(user, ntype: str, title: str, body: str):
    try:
        Notification.objects.create(user=user, type=ntype, title=title, body=body)
    except Exception:
        pass


def _restore_stock(order):
    from products.models import Product
    from django.db import transaction
    items = order.items.select_related('product').all()
    for item in items:
        if item.product:
            Product.objects.filter(pk=item.product.pk).update(
                stock=models.F('stock') + item.quantity
            )


PAYMENT_RATE_WINDOW = 60
PAYMENT_RATE_LIMIT  = 5


class OrderListCreateView(generics.ListCreateAPIView):
    serializer_class = OrderSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).prefetch_related('items__product').order_by('-created_at')

    def perform_create(self, serializer):
        # Payment and all order notifications are handled after Pesapal verification.
        serializer.save(user=self.request.user)


class OrderDetailView(generics.RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = (permissions.IsAuthenticated,)
    lookup_field = 'code'

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).prefetch_related('items__product')


class OrderCancelView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, code):
        try:
            order = Order.objects.get(code=code, user=request.user)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status != 'pending':
            return Response(
                {'detail': 'Only pending orders can be cancelled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            order.status = 'cancelled'
            order.save(update_fields=['status', 'updated_at'])
            _restore_stock(order)
        try:
            send_order_cancelled_email(order.user.name, order.user.email, order.code, 'Cancelled by customer.')
        except Exception:
            pass
        _notify(order.user, 'order', f'Order #{order.code} Cancelled', 'Your order has been cancelled as requested.')
        return Response(OrderSerializer(order).data)


class ServiceRatingView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, code):
        try:
            order = Order.objects.get(code=code, user=request.user)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status != 'delivered':
            return Response({'detail': 'Only delivered orders can be rated.'}, status=status.HTTP_400_BAD_REQUEST)

        if hasattr(order, 'service_rating'):
            return Response({'detail': 'You have already rated this order.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ServiceRatingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(order=order)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ReturnRequestView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, code):
        try:
            order = Order.objects.get(code=code, user=request.user)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status != 'delivered':
            return Response({'detail': 'Only delivered orders can be returned.'}, status=status.HTTP_400_BAD_REQUEST)

        if hasattr(order, 'return_request'):
            return Response({'detail': 'A return request already exists for this order.'}, status=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response({'detail': 'A reason is required.'}, status=status.HTTP_400_BAD_REQUEST)

        ret = ReturnRequest.objects.create(order=order, reason=reason)
        _notify(order.user, 'order', f'Return Request Submitted — #{order.code}', 'Your return request has been received and is under review.')
        return Response(ReturnRequestSerializer(ret).data, status=status.HTTP_201_CREATED)

    def get(self, request, code):
        try:
            order = Order.objects.get(code=code, user=request.user)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not hasattr(order, 'return_request'):
            return Response(None)
        return Response(ReturnRequestSerializer(order.return_request).data)


class ReturnRequestListView(generics.ListAPIView):
    serializer_class = ReturnRequestSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        return ReturnRequest.objects.filter(order__user=self.request.user).select_related('order').order_by('-created_at')


# ── Admin views ──────────────────────────────────────────────────────────────

class AdminOrderDetailView(generics.RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = (permissions.IsAdminUser,)
    lookup_field = 'code'

    def get_queryset(self):
        return Order.objects.prefetch_related('items__product')


class AdminOrderListView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = (permissions.IsAdminUser,)

    def get_queryset(self):
        qs = Order.objects.prefetch_related('items__product').order_by('-created_at')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class AdminOrderConfirmView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, code):
        try:
            order = Order.objects.select_related('user').get(code=code)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status != 'pending':
            return Response({'detail': 'Only pending orders can be confirmed.'}, status=status.HTTP_400_BAD_REQUEST)

        order.status = 'processing'
        order.status_changed_by = request.user
        order.save(update_fields=['status', 'status_changed_by', 'updated_at'])
        try:
            items = [{'name': i.product.name, 'qty': i.quantity, 'price': f'{i.price:,.0f}', 'image': _product_image(i.product)} for i in order.items.select_related('product').all()]
            send_order_confirmed_email(order.user.name, order.user.email, order.code, f'{order.total:,.0f}', items, order.delivery_address)
        except Exception:
            logger.exception('Failed to send order confirmed email for order %s', code)
        _notify(order.user, 'order', f'Order #{order.code} Confirmed', 'Your order has been confirmed and is being prepared for shipment.')
        return Response(OrderSerializer(order).data)


class AdminOrderCancelView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, code):
        try:
            order = Order.objects.select_related('user').get(code=code)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status == 'delivered':
            return Response({'detail': 'Delivered orders cannot be cancelled.'}, status=status.HTTP_400_BAD_REQUEST)
        if order.status == 'cancelled':
            return Response({'detail': 'Order is already cancelled.'}, status=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response({'detail': 'A cancellation reason is required.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            order.status = 'cancelled'
            order.cancel_reason = reason
            order.status_changed_by = request.user
            order.save(update_fields=['status', 'cancel_reason', 'status_changed_by', 'updated_at'])
            _restore_stock(order)
        try:
            send_order_cancelled_email(order.user.name, order.user.email, order.code, reason)
        except Exception:
            logger.exception('Failed to send order cancelled email for order %s', code)
        _notify(order.user, 'order', f'Order #{order.code} Cancelled', f'Your order was cancelled. Reason: {reason}')
        return Response(OrderSerializer(order).data)


class AdminOrderShipView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, code):
        try:
            order = Order.objects.select_related('user').get(code=code)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status != 'processing':
            return Response({'detail': 'Only confirmed orders can be marked as shipped.'}, status=status.HTTP_400_BAD_REQUEST)

        order.status = 'shipped'
        order.status_changed_by = request.user
        order.save(update_fields=['status', 'status_changed_by', 'updated_at'])
        try:
            send_order_shipped_email(order.user.name, order.user.email, order.code, order.delivery_address)
        except Exception:
            logger.exception('Failed to send order shipped email for order %s', code)
        _notify(order.user, 'order', f'Order #{order.code} Shipped', 'Your order is on its way! Our delivery team will contact you before arrival.')
        return Response(OrderSerializer(order).data)


class AdminOrderReadyForPickupView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, code):
        try:
            order = Order.objects.select_related('user').get(code=code)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status != 'shipped':
            return Response({'detail': 'Only shipped orders can be marked as ready for pickup.'}, status=status.HTTP_400_BAD_REQUEST)

        order.status = 'ready_for_pickup'
        order.status_changed_by = request.user
        order.save(update_fields=['status', 'status_changed_by', 'updated_at'])
        try:
            send_order_ready_for_pickup_email(order.user.name, order.user.email, order.code, order.delivery_address)
        except Exception:
            logger.exception('Failed to send ready for pickup email for order %s', code)
        _notify(order.user, 'order', f'Order #{order.code} Ready for Pickup', 'Your order is ready! Please come pick it up at your earliest convenience.')
        return Response(OrderSerializer(order).data)

class AdminOrderDeliverView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, code):
        try:
            order = Order.objects.select_related('user').get(code=code)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        if order.status != 'ready_for_pickup':
            return Response({'detail': 'Only ready-for-pickup orders can be marked as delivered.'}, status=status.HTTP_400_BAD_REQUEST)

        order.status = 'delivered'
        order.status_changed_by = request.user
        order.save(update_fields=['status', 'status_changed_by', 'updated_at'])
        try:
            items = [{
                'name': i.product.name,
                'qty': i.quantity,
                'price': f'{i.price:,.0f}',
                'image': _product_image(i.product),
            } for i in order.items.select_related('product').all()]
            send_order_delivered_email(
                order.user.name,
                order.user.email,
                order.code,
                f'{order.total:,.0f}',
                items,
                order.delivery_address,
            )
        except Exception:
            logger.exception('Failed to send order delivered email for order %s', code)
        _notify(order.user, 'order', f'Order #{order.code} Delivered', 'Your order has been delivered! Enjoy your new gadget. ❤️')
        # Schedule service + product rating emails and notifications 5 minutes after delivery.
        # This must never break the API if Redis/Celery is temporarily unavailable.
        try:
            send_product_rating_notifications.apply_async((order.id,), countdown=300)
        except Exception:
            logger.exception('Failed to queue product rating notifications for order %s', code)
        return Response(OrderSerializer(order).data)



# ── Pesapal Payment views ─────────────────────────────────────────────────────

def _pesapal_token():
    """Get a Pesapal OAuth token."""
    resp = http_requests.post(
        f"{settings.PESAPAL_BASE_URL}/api/Auth/RequestToken",
        json={'consumer_key': settings.PESAPAL_CONSUMER_KEY, 'consumer_secret': settings.PESAPAL_CONSUMER_SECRET},
        headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    logger.info('Pesapal token response: %s', data)
    if str(data.get('status')) != '200' or not data.get('token'):
        raise Exception(f"Pesapal auth failed: {data.get('error') or data}")
    return data['token']


def _register_ipn(token):
    """Get existing IPN ID or register new one."""
    # First try to get existing registered IPNs
    resp = http_requests.get(
        f"{settings.PESAPAL_BASE_URL}/api/URLSetup/GetIpnList",
        headers={'Accept': 'application/json', 'Authorization': f'Bearer {token}'},
        timeout=15,
    )
    if resp.ok:
        ipn_list = resp.json()
        if isinstance(ipn_list, list):
            for ipn in ipn_list:
                if ipn.get('url') == settings.PESAPAL_IPN_URL:
                    logger.info('Reusing existing IPN id=%s', ipn.get('ipn_id'))
                    return ipn['ipn_id']

    # Not found — register fresh
    resp = http_requests.post(
        f"{settings.PESAPAL_BASE_URL}/api/URLSetup/RegisterIPN",
        json={'url': settings.PESAPAL_IPN_URL, 'ipn_notification_type': 'GET'},
        headers={'Accept': 'application/json', 'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    logger.info('Pesapal IPN register response: %s', data)
    if not data.get('ipn_id'):
        raise Exception(f"Pesapal IPN registration failed: {data}")
    return data['ipn_id']


class InitiatePaymentView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @method_decorator(never_cache)
    def post(self, request, code):
        try:
            return self._handle(request, code)
        except Exception as e:
            logger.exception('Unhandled error in InitiatePaymentView for order %s', code)
            return Response({'detail': f'Server error: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _handle(self, request, code):
        rate_key = f'pay_attempt_{request.user.id}'
        attempts = cache.get(rate_key, 0)
        if attempts >= PAYMENT_RATE_LIMIT:
            return Response({'detail': 'Too many payment attempts. Please wait a minute.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        cache.set(rate_key, attempts + 1, PAYMENT_RATE_WINDOW)

        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(code=code, user=request.user)
                try:
                    if order.payment.status == 'completed':
                        return Response({'detail': 'Order already paid.'}, status=status.HTTP_400_BAD_REQUEST)
                except Exception:
                    pass
                if order.status not in ('pending', 'processing'):
                    return Response({'detail': 'This order cannot be paid.'}, status=status.HTTP_400_BAD_REQUEST)
        except Order.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            token = _pesapal_token()
            ipn_id = _register_ipn(token)
        except Exception as e:
            logger.exception('Pesapal auth/IPN failed for order %s', code)
            return Response({'detail': f'Pesapal setup failed: {str(e)}'}, status=status.HTTP_502_BAD_GATEWAY)

        try:
            payload = {
                'id': order.code,
                'currency': 'UGX',
                'amount': float(order.total),
                'description': f'Payment for order {order.code}',
                'callback_url': settings.PESAPAL_CALLBACK_URL,
                'notification_id': ipn_id,
                'billing_address': {
                    'email_address': request.user.email,
                    'phone_number': order.phone or request.user.phone,
                    'first_name': request.user.name.split()[0],
                    'last_name': ' '.join(request.user.name.split()[1:]) or request.user.name,
                },
            }
            resp = http_requests.post(
                f"{settings.PESAPAL_BASE_URL}/api/Transactions/SubmitOrderRequest",
                json=payload,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info('Pesapal SubmitOrderRequest response: %s', data)
            if not data.get('redirect_url'):
                raise Exception(f"Pesapal submit failed: {data}")
            with transaction.atomic():
                Payment.objects.update_or_create(
                    pesapal_order_tracking_id=data['order_tracking_id'],
                    defaults={
                        'order': order,
                        'merchant_reference': data.get('merchant_reference', order.code),
                        'amount': order.total,
                        'status': 'pending',
                    },
                )
            logger.info('Payment initiated: order=%s tracking=%s user=%s', order.code, data['order_tracking_id'], request.user.email)
            return Response({'redirect_url': data['redirect_url'], 'order_tracking_id': data['order_tracking_id']})
        except http_requests.HTTPError as e:
            logger.error('Pesapal HTTP error for order %s: %s', code, e)
            return Response({'detail': f'Payment gateway error: {str(e)}'}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception as e:
            logger.exception('Unexpected error for order %s', code)
            return Response({'detail': f'Payment failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PesapalIPNView(APIView):
    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        tracking_id = request.query_params.get('OrderTrackingId', '').strip()
        merchant_ref = request.query_params.get('OrderMerchantReference', '').strip()

        if not tracking_id:
            return Response({'detail': 'Missing OrderTrackingId'}, status=status.HTTP_400_BAD_REQUEST)

        # Only process tracking IDs we actually created — reject unknown ones
        try:
            payment = Payment.objects.select_related('order').get(pesapal_order_tracking_id=tracking_id)
        except Payment.DoesNotExist:
            logger.warning('IPN received for unknown tracking_id=%s', tracking_id)
            return Response({'detail': 'Unknown transaction'}, status=status.HTTP_404_NOT_FOUND)

        # Verify merchant reference matches what we stored
        if merchant_ref and payment.merchant_reference and merchant_ref != payment.merchant_reference:
            logger.warning('IPN merchant_ref mismatch: expected=%s got=%s', payment.merchant_reference, merchant_ref)
            return Response({'detail': 'Reference mismatch'}, status=status.HTTP_400_BAD_REQUEST)

        # Never downgrade a completed payment — prevents replay attacks
        if payment.status == 'completed':
            return Response({'orderNotificationType': 'IPNCHANGE', 'orderTrackingId': tracking_id, 'orderMerchantReference': merchant_ref, 'status': 200})

        try:
            token = _pesapal_token()
            resp = http_requests.get(
                f"{settings.PESAPAL_BASE_URL}/api/Transactions/GetTransactionStatus",
                params={'orderTrackingId': tracking_id},
                headers={'Accept': 'application/json', 'Authorization': f'Bearer {token}'},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            # Verify the amount Pesapal reports matches what we stored
            pesapal_amount = float(data.get('amount', 0))
            if pesapal_amount and abs(pesapal_amount - float(payment.amount)) > 0.01:
                logger.error('IPN amount mismatch: expected=%s pesapal=%s tracking=%s', payment.amount, pesapal_amount, tracking_id)
                return Response({'detail': 'Amount mismatch'}, status=status.HTTP_400_BAD_REQUEST)

            payment_status_desc = data.get('payment_status_description', '').lower()
            mapped = {'completed': 'completed', 'failed': 'failed', 'invalid': 'invalid', 'cancelled': 'cancelled'}.get(payment_status_desc, 'pending')

            with transaction.atomic():
                payment.status = mapped
                payment.payment_method = data.get('payment_method', '')
                payment.save(update_fields=['status', 'payment_method', 'updated_at'])

                order = payment.order
                if order:
                    from products.models import Product
                    if mapped == 'completed' and order.status in ('pending', 'processing'):
                        # This is the first completed transition because completed payments return above.
                        for item in order.items.select_related('product').all():
                            if item.product:
                                Product.objects.filter(pk=item.product.pk).update(
                                    stock=models.F('stock') - item.quantity
                                )
                        if order.status == 'pending':
                            order.status = 'processing'
                            order.save(update_fields=['status', 'updated_at'])

                        items = [{'name': i.product.name, 'qty': i.quantity, 'price': f'{i.price:,.0f}', 'image': _product_image(i.product)} for i in order.items.select_related('product').all()]
                        try:
                            send_admin_new_order_email(order.code, order.user.name, order.user.email, f'{order.total:,.0f}', items, order.delivery_address)
                        except Exception:
                            logger.exception('Failed to send paid order email for order %s', order.code)

                        _notify(order.user, 'order', f'Payment Confirmed - Order #{order.code}',
                                f'Payment received! UGX {order.total:,.0f}. Your order is being prepared.')

                        from users.models import User as UserModel
                        item_summary = ', '.join(f'{i["qty"]}x {i["name"]}' for i in items)
                        for admin in UserModel.objects.filter(is_staff=True):
                            _notify(admin, 'order', f'New Paid Order #{order.code}',
                                    f'{order.user.name} paid for an order. Items: {item_summary}. Total: UGX {order.total:,.0f}.')

                        order_items = order.items.select_related('product__trader__user').all()
                        notified_traders: dict = {}
                        for item in order_items:
                            trader_app = getattr(item.product, 'trader', None)
                            if not trader_app or not trader_app.user:
                                continue
                            tid = trader_app.id
                            if tid not in notified_traders:
                                notified_traders[tid] = {'user': trader_app.user, 'lines': []}
                            notified_traders[tid]['lines'].append(f'{item.product.name} x{item.quantity}')
                        for entry in notified_traders.values():
                            product_list = ', '.join(entry['lines'])
                            _notify(entry['user'], 'order', 'New Paid Order for Your Product!',
                                    f'A customer paid for: {product_list}. Order #{order.code}.')

                        try:
                            items = [{'name': i.product.name, 'qty': i.quantity, 'price': f'{i.price:,.0f}', 'image': _product_image(i.product)} for i in order.items.select_related('product').all()]
                            send_payment_successful_email(
                                order.user.name, order.user.email, order.code,
                                f'{order.total:,.0f}', items,
                                data.get('payment_method', ''),
                            )
                        except Exception:
                            logger.exception('Failed to send payment success email for order %s', order.code)
                    elif mapped in ('failed', 'invalid', 'cancelled') and order.status == 'pending':
                        order.status = 'cancelled'
                        order.cancel_reason = f'Payment {mapped}.'
                        order.save(update_fields=['status', 'cancel_reason', 'updated_at'])
                        _notify(order.user, 'order', f'Payment {mapped.title()} — Order #{order.code}',
                                f'Your payment {mapped}. Order #{order.code} has been cancelled. No money was deducted.')
                        try:
                            send_payment_failed_email(
                                order.user.name, order.user.email, order.code,
                                f'{order.total:,.0f}', mapped,
                            )
                        except Exception:
                            logger.exception('Failed to send payment failed email for order %s', order.code)

            logger.info('IPN processed: tracking=%s status=%s', tracking_id, mapped)
            return Response({'orderNotificationType': 'IPNCHANGE', 'orderTrackingId': tracking_id, 'orderMerchantReference': merchant_ref, 'status': 200})
        except http_requests.HTTPError as e:
            logger.error('Pesapal HTTP error on IPN for tracking=%s: %s', tracking_id, e)
            return Response({'detail': 'Gateway error'}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            logger.exception('Unexpected error on IPN for tracking=%s', tracking_id)
            return Response({'detail': 'Internal error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminPaymentsView(generics.ListAPIView):
    serializer_class = PaymentSerializer
    permission_classes = (permissions.IsAdminUser,)

    def get_queryset(self):
        qs = Payment.objects.select_related('order').order_by('-created_at')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs
