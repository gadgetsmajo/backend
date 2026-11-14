from users.models import Notification, User


def notify_advertising_admins(campaign):
    administrators = User.objects.filter(is_active=True, is_staff=True)
    notifications = [
        Notification(
            user=administrator,
            type='system',
            title='Advertising campaign needs review',
            body=(
                f'{campaign.trader.business_name} submitted '
                f'"{campaign.name}" for review.'
            ),
            action_url='/admin/advertising',
        )
        for administrator in administrators
    ]
    Notification.objects.bulk_create(notifications)


def notify_advertising_trader(trader, *, title, body):
    if not trader.user_id:
        return
    Notification.objects.create(
        user=trader.user,
        type='system',
        title=title,
        body=body,
        action_url=f'/trader/{trader.uuid}/advertising',
    )


def notify_campaign_status(campaign):
    status_messages = {
        'active': ('Advertising campaign active', 'is now active.'),
        'scheduled': ('Advertising campaign scheduled', 'has been approved and scheduled.'),
        'paused': ('Advertising campaign paused', 'is paused.'),
        'rejected': (
            'Advertising campaign rejected',
            f'was rejected. Reason: {campaign.rejection_reason or "Contact support for details."}',
        ),
        'cancelled': ('Advertising campaign cancelled', 'has been cancelled.'),
        'completed': ('Advertising campaign completed', 'has completed.'),
        'budget_exhausted': ('Advertising campaign budget reached', 'has reached its total budget.'),
    }
    notification = status_messages.get(campaign.status)
    if notification is None:
        return
    title, message = notification
    if campaign.status == 'paused':
        pause_reasons = {
            'insufficient_balance': ' The advertising wallet needs funds before it can continue.',
            'daily_budget_exhausted': ' It reached its daily budget.',
            'trader_paused': ' You paused it.',
            'admin_paused': ' It was paused by an administrator.',
        }
        if campaign.pause_reason:
            message += pause_reasons.get(
                campaign.pause_reason,
                f' Reason: {campaign.pause_reason}.',
            )
    notify_advertising_trader(
        campaign.trader,
        title=title,
        body=f'Your campaign "{campaign.name}" {message}',
    )


def notify_wallet_adjustment(trader, *, amount, balance, reason):
    direction = 'increased' if amount > 0 else 'decreased'
    notify_advertising_trader(
        trader,
        title='Advertising wallet adjusted',
        body=(
            f'Your advertising wallet was {direction} by UGX {abs(amount):,.2f}. '
            f'New balance: UGX {balance:,.2f}. Reason: {reason}'
        ),
    )
