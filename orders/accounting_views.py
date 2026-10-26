from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncMonth
from orders.models import Order, Payment


class AccountingSummaryView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        completed_payments = Payment.objects.filter(status='completed')

        total_revenue   = completed_payments.aggregate(t=Sum('amount'))['t'] or 0
        pending_payouts = Payment.objects.filter(status='pending').aggregate(t=Sum('amount'))['t'] or 0
        total_orders    = Order.objects.count()
        delivered       = Order.objects.filter(status='delivered').count()
        cancelled       = Order.objects.filter(status='cancelled').count()

        # Monthly revenue (last 6 months)
        monthly = (
            completed_payments
            .annotate(month=TruncMonth('created_at'))
            .values('month')
            .annotate(revenue=Sum('amount'), count=Count('id'))
            .order_by('month')
        )
        monthly_data = [
            {
                'month': m['month'].strftime('%b %Y'),
                'revenue': float(m['revenue']),
                'count': m['count'],
            }
            for m in monthly
        ]

        return Response({
            'total_revenue': float(total_revenue),
            'pending_payouts': float(pending_payouts),
            'total_orders': total_orders,
            'delivered_orders': delivered,
            'cancelled_orders': cancelled,
            'monthly': monthly_data,
        })


class AccountingTransactionsView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        payments = (
            Payment.objects
            .select_related('order')
            .order_by('-created_at')[:50]
        )
        data = [
            {
                'id': p.id,
                'order_code': p.order.code if p.order else None,
                'amount': float(p.amount),
                'currency': p.currency,
                'status': p.status,
                'payment_method': p.payment_method,
                'created_at': p.created_at,
            }
            for p in payments
        ]
        return Response(data)
