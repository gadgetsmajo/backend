from django.http import HttpResponse
from django.conf import settings

SAMPLE_ITEMS = [
    {'name': 'Samsung Galaxy A54', 'qty': 1, 'price': '850,000', 'image': 'https://res.cloudinary.com/d5qqtsou/image/upload/v1788691351/Majo_Gadgets_logo_an2hbc.png'},
    {'name': 'Wireless Earbuds Pro', 'qty': 2, 'price': '120,000', 'image': ''},
]


def _get_emails():
    from users.emails import (
        _wrap, _status_hero, _item_rows, _info_row,
        ICO_PACKAGE, ICO_MAP_PIN, ICO_PHONE, ICO_CHECK, ICO_STAR,
        ICO_HEART, ICO_TRUCK, ICO_SHOPPING, ICO_X_CIRCLE, ICO_LOCK,
        ICO_CLOCK, ICO_MAIL, IMG_WELCOME,
    )

    def welcome():
        hero = f'''
          <tr>
            <td style="padding:0;text-align:center;line-height:0">
              <img src="{IMG_WELCOME}" width="580" alt="Majo Gadgets" style="display:block;width:100%;max-width:580px;height:auto;margin:0 auto" />
            </td>
          </tr>
        '''
        return _wrap(f'''
          <div style="text-align:center;margin-bottom:24px">
            <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Welcome aboard, John!</h2>
            <p style="margin:0;font-size:14px;color:#64748B">Your account has been created successfully</p>
          </div>
          <p style="margin:0 0 20px;font-size:15px;color:#475569;line-height:1.7">
            We're thrilled to have you join the <strong>Majo Gadgets</strong> family. You're all set to start shopping.
          </p>
          <div style="padding:16px 20px;margin-bottom:28px">
            {_info_row(ICO_CHECK,    'Browse hundreds of quality gadgets')}
            {_info_row(ICO_STAR,     'Grab flash deals and exclusive offers')}
            {_info_row(ICO_HEART,    'Save your favourite items to your wishlist')}
            {_info_row(ICO_TRUCK,    'Fast and reliable delivery to your doorstep')}
          </div>
          <div style="text-align:center;margin:0 0 28px">
            <a href="{settings.FRONTEND_URL}" style="display:inline-block;padding:14px 32px;background:#071A2B !important;background-color:#071A2B !important;color:#ffffff !important;border:1px solid #071A2B;border-radius:0;font-weight:700;font-size:15px;text-decoration:none !important">
              Start Shopping &rarr;
            </a>
          </div>
          <p style="margin:28px 0 0;font-size:13px;color:#94A3B8">If you have any questions, just reply to this email.</p>
        ''', hero=hero)

    def order_confirmed():
        return _wrap(f'''
          <div style="text-align:center;margin-bottom:24px">
            <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Order Confirmed!</h2>
            <p style="margin:0;font-size:14px;color:#64748B">Hi <strong>John</strong>, we've received your order and it's being prepared.</p>
          </div>
          <div style="padding:16px 20px;margin-bottom:24px">
            <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Order Code</p>
            <p style="margin:0 0 12px;font-size:22px;font-weight:800;color:#1E3A8A;letter-spacing:1.5px">12345678-ABCDE</p>
            <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Delivering To</p>
            <p style="margin:0;font-size:13px;color:#334155">Central Region, Kampala, Nakawa</p>
          </div>
          <div style="padding:16px 20px;margin-bottom:24px">
            <p style="margin:0 0 12px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Items Ordered</p>
            <table width="100%" cellpadding="0" cellspacing="0">
              {_item_rows(SAMPLE_ITEMS)}
              <tr>
                <td colspan="2" style="padding-top:12px;font-size:14px;font-weight:700;color:#0F172A">Total</td>
                <td style="padding-top:12px;font-size:15px;font-weight:800;color:#1E3A8A;text-align:right">UGX 1,090,000</td>
              </tr>
            </table>
          </div>
          <p style="margin:0;font-size:13px;color:#94A3B8;line-height:1.6">We'll email you again once your order is shipped.</p>
        ''', hero=_status_hero('processing'))

    def order_shipped():
        return _wrap(f'''
          <div style="text-align:center;margin-bottom:24px">
            <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Your Order is On Its Way!</h2>
            <p style="margin:0;font-size:14px;color:#64748B">Hi <strong>John</strong>, your package has been shipped and is heading to you.</p>
          </div>
          <div style="padding:16px 20px;margin-bottom:24px">
            <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Order Code</p>
            <p style="margin:0 0 12px;font-size:22px;font-weight:800;color:#1E3A8A;letter-spacing:1.5px">12345678-ABCDE</p>
            <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Delivering To</p>
            <p style="margin:0;font-size:13px;color:#334155">Central Region, Kampala, Nakawa</p>
          </div>
          <div style="padding:16px 20px;margin-bottom:24px">
            {_info_row(ICO_PACKAGE, 'Your package is on the way')}
            {_info_row(ICO_MAP_PIN, 'Please ensure someone is available to receive it')}
            {_info_row(ICO_PHONE,   'Our delivery team may call you before arrival')}
          </div>
          <p style="margin:0;font-size:13px;color:#94A3B8;line-height:1.6">If you have any questions, reply to this email and we'll be happy to help.</p>
        ''', hero=_status_hero('shipped'))

    def order_delivered():
        return _wrap(f'''
          <div style="text-align:center;margin-bottom:24px">
            <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Order Delivered!</h2>
            <p style="margin:0;font-size:14px;color:#64748B">Hi <strong>John</strong>, your order has been successfully delivered.</p>
          </div>
          <div style="padding:16px 20px;margin-bottom:24px">
            {_info_row(ICO_CHECK,    'Order successfully delivered', '#065F46')}
            {_info_row(ICO_STAR,     "We'd love to hear your feedback", '#065F46')}
            {_info_row(ICO_SHOPPING, 'Thank you for shopping with Majo Gadgets', '#065F46')}
          </div>
          <p style="margin:0 0 20px;font-size:15px;color:#475569;line-height:1.7">Enjoyed your experience? Please take a moment to rate your order.</p>
          <div style="text-align:center">
            <a href="{settings.FRONTEND_URL}/rate/12345678-ABCDE" style="display:inline-block;padding:14px 32px;background:#071A2B !important;background-color:#071A2B !important;color:#ffffff !important;border:1px solid #071A2B;border-radius:0;font-weight:700;font-size:15px;text-decoration:none !important">Rate Your Order</a>
          </div>
          <p style="margin:28px 0 0;font-size:13px;color:#94A3B8;line-height:1.6">If you have any issues, please reply within 7 days.</p>
        ''', hero=_status_hero('delivered'))

    def order_cancelled():
        return _wrap(f'''
          <div style="text-align:center;margin-bottom:24px">
            <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Order Cancelled</h2>
            <p style="margin:0;font-size:14px;color:#64748B">Hi <strong>John</strong>, your order <strong>#12345678-ABCDE</strong> has been cancelled.</p>
          </div>
          <div style="padding:16px 20px;margin-bottom:24px">
            <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Cancellation Reason</p>
            <p style="margin:0;font-size:14px;color:#7F1D1D;line-height:1.6">Item out of stock at time of processing.</p>
          </div>
          <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.7">If you believe this was a mistake, please contact us.</p>
          <div style="text-align:center">
            <a href="{settings.FRONTEND_URL}" style="display:inline-block;padding:14px 32px;background:#071A2B !important;background-color:#071A2B !important;color:#ffffff !important;border:1px solid #071A2B;border-radius:0;font-weight:700;font-size:15px;text-decoration:none !important">Continue Shopping &rarr;</a>
          </div>
        ''')

    def return_approved():
        return _wrap(f'''
          <div style="text-align:center;margin-bottom:24px">
            <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Your Return Request Has Been Approved!</h2>
          </div>
          <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">Hi there!</p>
          <p style="margin:0 0 16px;font-size:13px;color:#64748B;line-height:1.7">Good news! Your return request for order <strong>#12345678-ABCDE</strong> has been reviewed and approved. We’ll guide you through the next steps to ensure your return process is as smooth and convenient as possible.</p>
          <p style="margin:0 0 16px;font-size:13px;color:#64748B;line-height:1.7">Thank you for your patience and for giving us the opportunity to make things right. We truly appreciate your trust in Majo Gadgets!</p>
          <p style="margin:24px 0 0;font-size:14px;color:#334155;font-weight:700">Thank you for choosing Majo Gadgets — your next great upgrade awaits!</p>
        ''')

    def refund_processed():
        return _wrap(f'''
          <div style="text-align:center;margin-bottom:24px">
            <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Your Refund Has Been Successfully Processed!</h2>
          </div>
          <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">Hi there!</p>
          <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">Good news! Your refund for order <strong>#12345678-ABCDE</strong> has been processed and will be sent back through the same payment method you used when placing your order.</p>
          <p style="margin:20px 0 8px;font-size:15px;color:#334155;font-weight:700">When will you receive your money?</p>
          <ul style="margin:0 0 16px;padding-left:22px;font-size:14px;color:#475569;line-height:1.8">
            <li><strong>Mobile Money:</strong> Please allow 1–3 business days for the refund to reflect in your account.</li>
            <li><strong>Card Payments:</strong> Please allow 4–7 business days for the refund to reflect in your account.</li>
          </ul>
          <p style="margin:0 0 16px;font-size:13px;color:#64748B;line-height:1.7">Please note that the actual time may depend on your payment provider. Weekends and public holidays are not counted as business days.</p>
          <p style="margin:0 0 16px;font-size:13px;color:#64748B;line-height:1.7">Thank you for your patience and understanding. We’re sorry things didn’t work out as expected, and we appreciate the opportunity to serve you.</p>
          <p style="margin:0 0 16px;font-size:13px;color:#64748B;line-height:1.7">We hope to welcome you back to Majo Gadgets soon for an even better shopping experience!</p>
          <p style="margin:24px 0 0;font-size:14px;color:#334155;font-weight:700">Majo Gadgets — your next great upgrade awaits!</p>
        ''')

    def password_reset():
        return _wrap(f'''
          <div style="text-align:center;margin-bottom:28px">
            <h2 style="margin:0 0 8px;font-size:22px;color:#0F172A">Password Reset Request</h2>
            <p style="margin:0;font-size:14px;color:#64748B">We received a request to reset your password</p>
          </div>
          <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
            Hi <strong>John</strong>, no worries — click the button below to create a new password.
          </p>
          <div style="padding:20px;margin-bottom:28px">
            <p style="margin:0 0 10px;font-size:12px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Security Notice</p>
            {_info_row(ICO_CLOCK, 'This link expires in <strong>1 hour</strong>', '#475569')}
            {_info_row(ICO_LOCK,  'For your security, this link can only be used once', '#475569')}
            {_info_row(ICO_MAIL,  'Only you should have access to this email', '#475569')}
          </div>
          <div style="text-align:center;margin-bottom:28px">
            <a href="#" style="display:inline-block;padding:14px 40px;background:#071A2B !important;background-color:#071A2B !important;color:#fff;border:1px solid #071A2B;border-radius:0;font-weight:700;font-size:15px;text-decoration:none">
              Reset My Password &rarr;
            </a>
          </div>
        ''')

    return {
        'welcome': welcome,
        'order_confirmed': order_confirmed,
        'order_shipped': order_shipped,
        'order_delivered': order_delivered,
        'order_cancelled': order_cancelled,
        'return_approved': return_approved,
        'refund_processed': refund_processed,
        'password_reset': password_reset,
    }


TEMPLATES = ['welcome', 'order_confirmed', 'order_shipped', 'order_delivered', 'order_cancelled', 'return_approved', 'refund_processed', 'password_reset']

NAV_LINKS = ' &nbsp;|&nbsp; '.join(
    f'<a href="?t={key}" style="color:#94A3B8;font-weight:600;text-decoration:none;font-size:13px">{key.replace("_", " ").title()}</a>'
    for key in TEMPLATES
)


def email_preview(request):
    if not settings.DEBUG:
        from django.http import Http404
        raise Http404

    template = request.GET.get('t', 'welcome')
    previews = _get_emails()
    html = previews.get(template, previews['welcome'])()

    nav = f'''
    <div style="position:fixed;top:0;left:0;right:0;z-index:9999;background:#071A2B;padding:10px 24px;font-family:Inter,sans-serif;display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <span style="color:#475569;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px">Email Preview</span>
      <span style="color:#334155">|</span>
      {NAV_LINKS}
    </div>
    <div style="height:44px"></div>
    '''

    return HttpResponse(nav + html)
