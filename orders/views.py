from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.core.cache import cache
from django.db import transaction, models
from accounting.models import Refund as AccountingRefund
from .models import Order, ServiceRating, Payment, ReturnRequest
from .serializers import OrderSerializer, ServiceRatingSerializer, PaymentSerializer, ReturnRequestSerializer, AdminReturnRequestSerializer
from .tasks import send_product_rating_notifications
from users.models import CartItem, Notification
from settings_app.models import District
from products.models import Product
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
    send_return_approved_email,
    send_refund_processed_email,
)
import requests as http_requests
import logging
from decimal import Decimal, InvalidOperation

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


class CartQuoteView(APIView):
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        district = None
        district_id = request.data.get('district_id')
        if district_id not in (None, ''):
            try:
                district = District.objects.get(pk=int(district_id))
            except (District.DoesNotExist, TypeError, ValueError):
                return Response({'detail': 'Select a valid delivery district.'}, status=status.HTTP_400_BAD_REQUEST)

        if request.user.is_authenticated:
            cart_items = list(CartItem.objects.filter(user=request.user).order_by('product_id'))
            requested_items = [(item.product_id, item.quantity, item.pk) for item in cart_items]
            if len(requested_items) > 100:
                return Response({'detail': 'Your cart has too many different products.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            raw_items = request.data.get('items')
            if not isinstance(raw_items, list):
                return Response({'detail': 'Cart items are required.'}, status=status.HTTP_400_BAD_REQUEST)
            if len(raw_items) > 100:
                return Response({'detail': 'Your cart has too many different products.'}, status=status.HTTP_400_BAD_REQUEST)
            requested_items = []
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    return Response({'detail': 'Invalid cart item.'}, status=status.HTTP_400_BAD_REQUEST)
                try:
                    product_id = int(raw_item.get('product_id'))
                    quantity = int(raw_item.get('quantity'))
                except (TypeError, ValueError):
                    return Response({'detail': 'Invalid cart item.'}, status=status.HTTP_400_BAD_REQUEST)
                if product_id < 1 or not 1 <= quantity <= 100:
                    return Response({'detail': 'Invalid cart item quantity.'}, status=status.HTTP_400_BAD_REQUEST)
                requested_items.append((product_id, quantity, None))

        if len({product_id for product_id, _, _ in requested_items}) != len(requested_items):
            return Response({'detail': 'Duplicate products are not allowed in the cart.'}, status=status.HTTP_400_BAD_REQUEST)
        if any(not 1 <= quantity <= 100 for _, quantity, _ in requested_items):
            return Response({'detail': 'Invalid cart item quantity.'}, status=status.HTTP_400_BAD_REQUEST)

        products = {
            product.pk: product
            for product in Product.objects.filter(
                pk__in=[product_id for product_id, _, _ in requested_items],
                is_active=True,
            )
        }
        if len(products) != len(requested_items):
            return Response(
                {'detail': 'A product in your cart is no longer available. Please refresh your cart.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        items = []
        subtotal = 0
        product_delivery_total = 0
        for product_id, quantity, cart_item_id in requested_items:
            product = products[product_id]
            if quantity > product.stock:
                return Response(
                    {'detail': f'Not enough stock for "{product.name}". Available: {product.stock}.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            line_total = product.price * quantity
            subtotal += line_total
            product_delivery_total += product.delivery_fee
            items.append({
                'id': cart_item_id or product_id,
                'product_id': product_id,
                'product_name': product.name,
                'product_price': product.price,
                'product_image': product.image.url if product.image else None,
                'product_slug': product.slug,
                'product_category': product.category.name if product.category else '',
                'product_rating': product.rating,
                'quantity': quantity,
                'delivery_fee': product.delivery_fee,
                'line_total': line_total,
            })

        delivery_fee = district.price if district else product_delivery_total
        return Response({
            'items': items,
            'subtotal': subtotal,
            'delivery_fee': delivery_fee,
            'total': subtotal + delivery_fee,
        })


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


class AdminReturnRequestListView(generics.ListAPIView):
    serializer_class = AdminReturnRequestSerializer
    permission_classes = (permissions.IsAdminUser,)

    def get_queryset(self):
        return ReturnRequest.objects.select_related('order__user', 'order__payment').order_by('-created_at')


class AdminReturnRequestApproveView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, pk):
        if not settings.PESAPAL_REFUND_USERNAME:
            return Response(
                {'detail': 'Automatic refunds are not configured. Check the payment provider refund settings.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            with transaction.atomic():
                return_request = ReturnRequest.objects.select_for_update().select_related(
                    'order__user', 'order__payment'
                ).get(pk=pk)
                if return_request.status != 'pending':
                    return Response({'detail': 'Only pending return requests can be approved.'}, status=status.HTTP_400_BAD_REQUEST)

                try:
                    payment = return_request.order.payment
                except Payment.DoesNotExist:
                    return Response({'detail': 'This order has no recorded payment to refund.'}, status=status.HTTP_400_BAD_REQUEST)
                if payment.status != 'completed':
                    return Response({'detail': 'Only completed payments can be refunded.'}, status=status.HTTP_400_BAD_REQUEST)

                return_request.status = 'processing'
                return_request.refund_amount = payment.amount
                return_request.save(update_fields=['status', 'refund_amount', 'updated_at'])
        except ReturnRequest.DoesNotExist:
            return Response({'detail': 'Return request not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            token = _pesapal_token()
            if not payment.confirmation_code:
                status_response = http_requests.get(
                    f'{settings.PESAPAL_BASE_URL}/api/Transactions/GetTransactionStatus',
                    params={'orderTrackingId': payment.pesapal_order_tracking_id},
                    headers={'Accept': 'application/json', 'Authorization': f'Bearer {token}'},
                    timeout=15,
                )
                status_response.raise_for_status()
                transaction_data = status_response.json()
                verified_amount = float(transaction_data.get('amount', 0))
                if abs(verified_amount - float(payment.amount)) > 0.01:
                    raise ValueError('Pesapal payment amount does not match the recorded payment.')
                if transaction_data.get('payment_status_description', '').lower() != 'completed':
                    raise ValueError('Pesapal does not report this payment as completed.')
                payment.confirmation_code = transaction_data.get('confirmation_code', '')
                if not payment.confirmation_code:
                    raise ValueError('Pesapal has not provided a confirmation code for this payment.')
                payment.save(update_fields=['confirmation_code', 'updated_at'])

            refund_response = http_requests.post(
                f'{settings.PESAPAL_BASE_URL}/api/Transactions/RefundRequest',
                json={
                    'confirmation_code': payment.confirmation_code,
                    'amount': float(payment.amount),
                    'username': settings.PESAPAL_REFUND_USERNAME,
                    'remarks': return_request.reason[:250],
                },
                headers={'Accept': 'application/json', 'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'},
                timeout=15,
            )
            refund_response.raise_for_status()
            refund_data = refund_response.json()
            response_code = str(refund_data.get('status', refund_data.get('error', '')))
            if response_code != '200':
                error = refund_data.get('error')
                error_message = error.get('message') if isinstance(error, dict) else error
                raise ValueError(error_message or refund_data.get('message') or 'Pesapal did not accept the refund request.')
        except Exception as exc:
            logger.exception('Pesapal refund request failed for return %s', pk)
            return_request.status = 'refund_failed'
            return_request.admin_note = f'Refund request failed. Verify the transaction with the payment provider before taking further action. {str(exc)[:500]}'
            return_request.save(update_fields=['status', 'admin_note', 'updated_at'])
            return Response({'detail': return_request.admin_note}, status=status.HTTP_502_BAD_GATEWAY)

        return_request.status = 'approved'
        return_request.admin_note = 'Return approved. The refund request has been accepted and is being processed to the original payment method. This does not confirm that funds have been credited yet.'
        return_request.save(update_fields=['status', 'admin_note', 'updated_at'])
        _notify(
            return_request.order.user,
            'order',
            f'Return Approved — #{return_request.order.code}',
            f'Your return was approved. Your refund request for UGX {payment.amount:,.0f} is being processed to your original payment method.',
        )
        try:
            send_return_approved_email(
                return_request.order.user.email,
                return_request.order.code,
            )
        except Exception:
            logger.exception('Failed to send return approval email for return %s', pk)
        return Response(AdminReturnRequestSerializer(return_request).data)


class AdminReturnRequestRefundedView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, pk):
        try:
            with transaction.atomic():
                return_request = ReturnRequest.objects.select_for_update().select_related(
                    'order__user', 'order__payment'
                ).get(pk=pk)
                if return_request.status != 'approved':
                    return Response({'detail': 'Only approved return requests can be marked as refunded.'}, status=status.HTTP_400_BAD_REQUEST)

                refund_amount = return_request.refund_amount or return_request.order.total
                try:
                    refund_method = return_request.order.payment.payment_method
                except Payment.DoesNotExist:
                    refund_method = ''

                AccountingRefund.objects.create(
                    order=return_request.order,
                    customer_name=return_request.order.user.name,
                    return_reason=return_request.reason,
                    refund_amount=refund_amount,
                    refund_method=refund_method,
                    status='completed',
                )
                return_request.status = 'refunded'
                return_request.admin_note = 'Refund confirmed as processed to the original payment method.'
                return_request.save(update_fields=['status', 'admin_note', 'updated_at'])
        except ReturnRequest.DoesNotExist:
            return Response({'detail': 'Return request not found.'}, status=status.HTTP_404_NOT_FOUND)
        _notify(
            return_request.order.user,
            'order',
            f'Refund Processed — #{return_request.order.code}',
            f'Your refund of UGX {return_request.refund_amount:,.0f} has been confirmed as processed.',
        )
        try:
            send_refund_processed_email(
                return_request.order.user.email,
                return_request.order.code,
            )
        except Exception:
            logger.exception('Failed to send refund processed email for return %s', pk)
        return Response(AdminReturnRequestSerializer(return_request).data)


class AdminReturnRequestRejectView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request, pk):
        try:
            return_request = ReturnRequest.objects.select_related('order__user').get(pk=pk)
        except ReturnRequest.DoesNotExist:
            return Response({'detail': 'Return request not found.'}, status=status.HTTP_404_NOT_FOUND)

        if return_request.status != 'pending':
            return Response({'detail': 'Only pending return requests can be rejected.'}, status=status.HTTP_400_BAD_REQUEST)

        return_request.status = 'rejected'
        return_request.admin_note = request.data.get('admin_note', '').strip()
        return_request.save(update_fields=['status', 'admin_note', 'updated_at'])
        _notify(
            return_request.order.user,
            'order',
            f'Return Update — #{return_request.order.code}',
            return_request.admin_note or 'Your return request was reviewed and could not be approved.',
        )
        return Response(AdminReturnRequestSerializer(return_request).data)


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
        qs = Order.objects.prefetch_related('items__product').exclude(
            return_request__status='refunded'
        ).order_by('-created_at')
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
        # Schedule product review emails and notifications 5 minutes after delivery.
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
        if not all((
            settings.PESAPAL_CONSUMER_KEY,
            settings.PESAPAL_CONSUMER_SECRET,
            settings.PESAPAL_IPN_URL,
            settings.PESAPAL_CALLBACK_URL,
        )):
            logger.error('Pesapal configuration is incomplete for order %s', code)
            return Response({'detail': 'Pesapal payment is not configured on the server.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

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
            if not data.get('redirect_url') or not data.get('order_tracking_id'):
                raise Exception(f"Pesapal submit failed: {data}")
            with transaction.atomic():
                payment, _ = Payment.objects.get_or_create(order=order)
                payment.pesapal_order_tracking_id = data['order_tracking_id']
                payment.merchant_reference = data.get('merchant_reference', order.code)
                payment.amount = order.total
                payment.currency = 'UGX'
                payment.status = 'pending'
                payment.payment_method = ''
                payment.description = f'Payment for order {order.code}'
                payment.save()
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

            try:
                pesapal_amount = Decimal(str(data['amount']))
            except (KeyError, TypeError, ValueError, InvalidOperation):
                logger.error('IPN response has no valid amount for tracking=%s', tracking_id)
                return Response({'detail': 'Invalid payment amount.'}, status=status.HTTP_400_BAD_REQUEST)

            pesapal_currency = str(data.get('currency_code') or data.get('currency') or '').upper()
            provider_reference = str(data.get('merchant_reference') or '').strip()
            provider_tracking_id = str(data.get('order_tracking_id') or '').strip()
            if (
                not pesapal_amount.is_finite()
                or pesapal_amount <= 0
                or pesapal_amount != payment.amount
                or not payment.order
                or payment.amount != payment.order.total
                or pesapal_currency != payment.currency.upper()
                or (payment.merchant_reference and provider_reference != payment.merchant_reference)
                or (provider_tracking_id and provider_tracking_id != tracking_id)
            ):
                logger.error(
                    'IPN verification mismatch: expected_amount=%s reported_amount=%s expected_currency=%s '
                    'reported_currency=%s tracking=%s',
                    payment.amount, pesapal_amount, payment.currency, pesapal_currency, tracking_id,
                )
                return Response({'detail': 'Payment verification failed.'}, status=status.HTTP_400_BAD_REQUEST)

            payment_status_desc = data.get('payment_status_description', '').lower()
            mapped = {'completed': 'completed', 'failed': 'failed', 'invalid': 'invalid', 'cancelled': 'cancelled'}.get(payment_status_desc, 'pending')

            with transaction.atomic():
                payment = Payment.objects.select_for_update().select_related('order__user').get(pk=payment.pk)
                if payment.status == 'completed':
                    return Response({'orderNotificationType': 'IPNCHANGE', 'orderTrackingId': tracking_id, 'orderMerchantReference': merchant_ref, 'status': 200})

                payment.status = mapped
                payment.payment_method = data.get('payment_method', '')
                payment.confirmation_code = data.get('confirmation_code', '')
                payment.save(update_fields=['status', 'payment_method', 'confirmation_code', 'updated_at'])

                order = payment.order
                if order:
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
