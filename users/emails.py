from html import escape

import resend
from django.conf import settings


def _send(payload: dict):
    resend.api_key = settings.RESEND_API_KEY
    payload.setdefault('reply_to', settings.SUPPORT_EMAIL)
    resend.Emails.send(payload)

FROM = 'Majo Gadgets <support@majogadgets.com>'
LOGO = 'https://res.cloudinary.com/fhklnn0f/image/upload/v1789111152/Majo_Gadgets_logo_an2hbc.png'
IMG_CART = 'https://res.cloudinary.com/fhklnn0f/image/upload/v1789551363/shopping_cart.png'
IMG_WELCOME = 'https://res.cloudinary.com/fhklnn0f/image/upload/v1789298565/OG.png'

# ── Icon paths ───────────────────────────────────────────────────────────────
ICO_CHECK       = '<polyline points="20 6 9 17 4 12"/>'
ICO_PACKAGE     = '<path d="M16.5 9.4 7.55 4.24"/><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 2 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.29 7 12 12 20.71 7"/><line x1="12" y1="22" x2="12" y2="12"/>'
ICO_TRUCK       = '<rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>'
ICO_STAR        = '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>'
ICO_X_CIRCLE    = '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>'
ICO_LOCK        = '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
ICO_CLOCK       = '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>'
ICO_MAIL        = '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>'
ICO_SHOPPING    = '<circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>'
ICO_HEART       = '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>'
ICO_SETTINGS    = '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'
ICO_MAP_PIN     = '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>'
ICO_PHONE       = '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13a19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.56 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 9.91a16 16 0 0 0 6.08 6.08l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/>'

# ── Email-safe glyphs ────────────────────────────────────────────────────────
def _icon(path_d: str, color: str = '#ffffff', size: int = 20) -> str:
    if path_d == ICO_SHOPPING:
        return f'<img src="{IMG_CART}" width="{size}" height="{size}" alt="Shopping cart" style="display:inline-block;vertical-align:middle" />'

    glyph_map = {
        ICO_CHECK: '+',
        ICO_PACKAGE: '#',
        ICO_TRUCK: '>',
        ICO_STAR: '*',
        ICO_X_CIRCLE: 'x',
        ICO_LOCK: '!',
        ICO_CLOCK: 'o',
        ICO_MAIL: '@',
        ICO_HEART: '+',
        ICO_SETTINGS: '*',
        ICO_MAP_PIN: '@',
        ICO_PHONE: 'tel',
    }
    glyph = glyph_map.get(path_d, '.')
    return (
        f'<span style="display:inline-block;font-size:{size}px;line-height:1;color:{color};'
        f'font-family:Arial,Helvetica,sans-serif;font-weight:700;vertical-align:middle">{glyph}</span>'
    )


BASE = '''
<body style="margin:0;padding:0;background:#F1F5F9;font-family:Inter,Arial,sans-serif">
  <style>
    a, a:link, a:visited, a:hover, a:active { color:#ffffff !important; text-decoration:none !important; }
  </style>
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F1F5F9;padding:40px 0">
    <tr><td align="center">
      <table width="580" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.07)">
        <tr>
          <td style="background:#ffffff;padding:28px 40px;text-align:center;border-bottom:1px solid #E2E8F0">
            <img src="{logo}" height="48" alt="Majo Gadgets" style="display:block;margin:0 auto" />
          </td>
        </tr>
        {hero}
        <tr><td style="padding:36px 40px 28px">{body}</td></tr>
        <tr><td style="padding:0 40px"><hr style="border:none;border-top:1px solid #E2E8F0;margin:0" /></td></tr>
        <tr>
          <td style="padding:20px 40px;text-align:center">
            <p style="margin:0 0 4px;font-size:13px;color:#111111">Majo Gadgets &mdash; Quality gadgets, great value.</p>
            <p style="margin:0;font-size:11px;color:#333333">&copy; 2026 Majo Gadgets. All rights reserved.</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
'''


def _wrap(body: str, hero: str = '') -> str:
  return BASE.replace('{logo}', LOGO).replace('{hero}', hero).replace('{body}', body)


# ── Order status images ──────────────────────────────────────────────────────
_STEP_IMGS = [
    ('pending',          'https://res.cloudinary.com/fhklnn0f/image/upload/v1789549511/Order_placed.png',       'Placed'),
    ('processing',       'https://res.cloudinary.com/fhklnn0f/image/upload/v1789549477/order_confirmed.png',    'Confirmed'),
    ('shipped',          'https://res.cloudinary.com/fhklnn0f/image/upload/v1789549510/Shipped_order.png',      'Shipped'),
    ('ready_for_pickup', 'https://res.cloudinary.com/fhklnn0f/image/upload/v1789549694/ready_for_pickup.png',   'Ready for Pickup'),
    ('delivered',        'https://res.cloudinary.com/fhklnn0f/image/upload/v1789549452/Delivered.png',          'Delivered'),
]


def _status_hero(status: str) -> str:
    image_url, label = next(
        ((image_url, label) for key, image_url, label in _STEP_IMGS if key == status),
        (_STEP_IMGS[0][1], _STEP_IMGS[0][2]),
    )
    return f'''
      <tr>
        <td style="padding:0;text-align:center;line-height:0">
          <img src="{image_url}" width="360" alt="Order status: {label}" style="display:block;width:100%;max-width:360px;height:auto;margin:0 auto" />
        </td>
      </tr>
    '''


def _item_rows(items: list) -> str:
    rows = ''
    for item in items:
        img_html = (
            f'<img src="{item["image"]}" width="56" height="56" alt="" style="border-radius:8px;object-fit:cover;display:block" />'
            if item.get('image') else
            f'<div style="width:56px;height:56px;background:#F1F5F9;border-radius:8px;text-align:center;line-height:56px">{_icon(ICO_PACKAGE, "#CBD5E1", 24)}</div>'
        )
        rows += f'''
        <tr>
          <td style="padding:10px 0;border-bottom:1px solid #F1F5F9;vertical-align:middle;width:68px">{img_html}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #F1F5F9;vertical-align:middle">
            <p style="margin:0 0 2px;font-size:13px;font-weight:600;color:#111111">{item["name"]}</p>
            <p style="margin:0;font-size:12px;color:#333333">Qty: {item["qty"]}</p>
          </td>
          <td style="padding:10px 0;border-bottom:1px solid #F1F5F9;vertical-align:middle;text-align:right;white-space:nowrap">
            <p style="margin:0;font-size:13px;font-weight:700;color:#111111">UGX {item["price"]}</p>
          </td>
        </tr>'''
    return rows


def _info_row(icon_path: str, text: str, color: str = '#111111') -> str:
    return f'''
    <p style="margin:0 0 10px;font-size:14px;color:{color};display:flex;align-items:center;gap:8px">
      {_icon(icon_path, color, 16)}&nbsp;&nbsp;{text}
    </p>'''


def _bullet_row(text: str, color: str = '#334155') -> str:
    return f'''
    <li style="margin:0 0 10px;font-size:14px;color:{color};line-height:1.6;list-style:disc;padding-left:4px">{text}</li>'''


def send_welcome_email(name: str, email: str):
    hero = f'''
        <tr>
          <td style="padding:0;text-align:center;line-height:0">
            <img src="{IMG_WELCOME}" width="580" alt="Majo Gadgets" style="display:block;width:100%;max-width:580px;height:auto;margin:0 auto" />
          </td>
        </tr>
    '''
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#111111">Welcome aboard, {name}!</h2>
        <p style="margin:0;font-size:14px;color:#333333">Your account has been created successfully</p>
      </div>
      <p style="margin:0 0 20px;font-size:15px;color:#111111;line-height:1.7">
        We&#39;re thrilled to have you join the <strong>Majo Gadgets</strong> family. You&#39;re all set to start shopping.
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
      <p style="margin:28px 0 0;font-size:13px;color:#333333">If you have any questions, just reply to this email — we&#39;re always happy to help.</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': 'Welcome to Majo Gadgets!', 'html': _wrap(body, hero=hero)})


def send_admin_new_order_email(order_code: str, customer_name: str, customer_email: str, total: str, items: list, delivery_address: str):
    admin_url = f'{settings.FRONTEND_URL}/admin/orders/{order_code}'
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <img src="{IMG_CART}" width="56" height="56" alt="" style="display:block;margin:0 auto 12px" />
        <h2 style="margin:0 0 6px;font-size:22px;color:#111111">New Order Received!</h2>
        <p style="margin:0;font-size:14px;color:#333333">A customer just placed an order.</p>
      </div>

      <div style="padding:16px 20px;margin-bottom:24px">
        <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#333333;text-transform:uppercase;letter-spacing:0.5px">Order Code</p>
        <p style="margin:0 0 12px;font-size:22px;font-weight:800;color:#111111;letter-spacing:1.5px">{order_code}</p>
        <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#333333;text-transform:uppercase;letter-spacing:0.5px">Customer</p>
        <p style="margin:0 0 12px;font-size:13px;color:#111111">{customer_name} &mdash; {customer_email}</p>
        <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#333333;text-transform:uppercase;letter-spacing:0.5px">Delivery Address</p>
        <p style="margin:0 0 16px;font-size:13px;color:#111111">{delivery_address}</p>
        <hr style="border:none;border-top:1px solid #E2E8F0;margin:0 0 16px" />
        <p style="margin:0 0 12px;font-size:11px;font-weight:700;color:#333333;text-transform:uppercase;letter-spacing:0.5px">Items Ordered</p>
        <table width="100%" cellpadding="0" cellspacing="0">
          {_item_rows(items)}
          <tr>
            <td colspan="2" style="padding-top:12px;font-size:14px;font-weight:700;color:#111111">Total</td>
            <td style="padding-top:12px;font-size:15px;font-weight:800;color:#111111;text-align:right">UGX {total}</td>
          </tr>
        </table>
      </div>

      <div style="text-align:center">
        <a href="{admin_url}" style="display:inline-block;padding:14px 32px;background:#071A2B !important;background-color:#071A2B !important;color:#ffffff !important;border:1px solid #071A2B;border-radius:0;font-weight:700;font-size:15px;text-decoration:none !important">
          View &amp; Confirm Order &rarr;
        </a>
      </div>
      <p style="margin:16px 0 0;font-size:13px;color:#333333">Or track it at: <a href="{settings.FRONTEND_URL}/orders/{order_code}" style="color:#1E3A8A !important">{settings.FRONTEND_URL}/orders/{order_code}</a></p>
    '''
    _send({'from': FROM, 'to': settings.ADMIN_EMAIL, 'reply_to': settings.ADMIN_EMAIL, 'subject': f'New Order #{order_code} — UGX {total}', 'html': _wrap(body)})


def send_order_placed_email(name: str, email: str, order_code: str, total: str, items: list, delivery_address: str):
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <img src="{IMG_CART}" width="56" height="56" alt="" style="display:block;margin:0 auto 12px" />
        <h2 style="margin:0 0 6px;font-size:22px;color:#111111">Order Placed!</h2>
        <p style="margin:0;font-size:14px;color:#333333">Hi <strong>{name}</strong>, we&#39;ve received your order.</p>
      </div>

      <p style="margin:0 0 16px;font-size:15px;color:#111111;line-height:1.7">
        Thank you for your order! Your order <strong>#{order_code}</strong> has been placed and is awaiting confirmation.
      </p>
      <p style="margin:0 0 24px;font-size:15px;color:#111111;line-height:1.7">
        We&#39;ll notify you once it&#39;s confirmed and being prepared for shipment.
      </p>

      <div style="padding:16px 20px;margin-bottom:24px">
        <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#333333;text-transform:uppercase;letter-spacing:0.5px">Order Code</p>
        <p style="margin:0 0 12px;font-size:22px;font-weight:800;color:#111111;letter-spacing:1.5px">{order_code}</p>
        <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#333333;text-transform:uppercase;letter-spacing:0.5px">Delivering To</p>
        <p style="margin:0 0 16px;font-size:13px;color:#111111">{delivery_address}</p>
        <hr style="border:none;border-top:1px solid #E2E8F0;margin:0 0 16px" />
        <p style="margin:0 0 12px;font-size:11px;font-weight:700;color:#333333;text-transform:uppercase;letter-spacing:0.5px">Items Ordered</p>
        <table width="100%" cellpadding="0" cellspacing="0">
          {_item_rows(items)}
          <tr>
            <td colspan="2" style="padding-top:12px;font-size:14px;font-weight:700;color:#111111">Total</td>
            <td style="padding-top:12px;font-size:15px;font-weight:800;color:#111111;text-align:right">UGX {total}</td>
          </tr>
        </table>
      </div>

      <p style="margin:0 0 12px;font-size:15px;color:#111111;line-height:1.7">Thank you for shopping with Majo Gadgets!</p>
      <p style="margin:0;font-size:13px;color:#333333;line-height:1.6">— The Majo Gadgets Team</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Order Placed — #{order_code}', 'html': _wrap(body, hero=_status_hero('pending'))})


def send_order_confirmed_email(name: str, email: str, order_code: str, total: str, items: list, delivery_address: str):
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#111111">Order Confirmed!</h2>
        <p style="margin:0;font-size:14px;color:#333333">Hi <strong>{name}</strong>,</p>
      </div>

      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        Great news! Your order <strong>#{order_code}</strong> has been confirmed.
      </p>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        We’re now preparing your items for shipment.
      </p>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        <strong>Order total:</strong> UGX {total}
      </p>
      <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.7">
        We’ll keep you updated as your order moves through the delivery process.
      </p>

      <div style="padding:16px 20px;margin-bottom:24px">
        <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Order Code</p>
        <p style="margin:0 0 12px;font-size:22px;font-weight:800;color:#0F172A;letter-spacing:1.5px">{order_code}</p>
        <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Delivering To</p>
        <p style="margin:0 0 16px;font-size:13px;color:#334155">{delivery_address}</p>
        <hr style="border:none;border-top:1px solid #E2E8F0;margin:0 0 16px" />
        <p style="margin:0 0 12px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Items Ordered</p>
        <table width="100%" cellpadding="0" cellspacing="0">
          {_item_rows(items)}
          <tr>
            <td colspan="2" style="padding-top:12px;font-size:14px;font-weight:700;color:#0F172A">Total</td>
            <td style="padding-top:12px;font-size:15px;font-weight:800;color:#0F172A;text-align:right">UGX {total}</td>
          </tr>
        </table>
      </div>

      <p style="margin:0 0 12px;font-size:15px;color:#475569;line-height:1.7">Thank you for shopping with Majo Gadgets! {_icon(ICO_SHOPPING, '#475569', 16)}</p>
      <p style="margin:0;font-size:13px;color:#94A3B8;line-height:1.6">— The Majo Gadgets Team</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Order Confirmed — #{order_code}', 'html': _wrap(body, hero=_status_hero('processing'))})


def send_order_shipped_email(name: str, email: str, order_code: str, delivery_address: str):
    safe_address = (delivery_address or '').replace('{', '{{').replace('}', '}}')
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Your Order is On Its Way!</h2>
        <p style="margin:0;font-size:14px;color:#64748B">Hi <strong>{name}</strong>, your package has been shipped and is heading to you.</p>
      </div>

      <div style="padding:16px 20px;margin-bottom:24px">
        <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Order Code</p>
        <p style="margin:0 0 12px;font-size:22px;font-weight:800;color:#0F172A;letter-spacing:1.5px">{order_code}</p>
        <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Delivering To</p>
        <p style="margin:0 0 16px;font-size:13px;color:#334155">{safe_address}</p>
        <hr style="border:none;border-top:1px solid #E2E8F0;margin:0 0 16px" />
        {_info_row(ICO_PACKAGE,  'Your package is on the way')}
        {_info_row(ICO_MAP_PIN,  'Please ensure someone is available to receive it')}
        {_info_row(ICO_PHONE,    'Our delivery team may call you before arrival')}
      </div>

      <p style="margin:0;font-size:13px;color:#94A3B8;line-height:1.6">If you have any questions about your delivery, reply to this email and we&#39;ll be happy to help.</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Your Order is Shipped — #{order_code}', 'html': _wrap(body, hero=_status_hero('shipped'))})


def send_order_ready_for_pickup_email(name: str, email: str, order_code: str, pickup_address: str = ''):
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Your Order is Ready for Pickup!</h2>
        <p style="margin:0;font-size:14px;color:#64748B">Hi <strong>{name}</strong>, your order is waiting for you.</p>
      </div>

      <div style="padding:16px 20px;margin-bottom:24px">
        <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Order Code</p>
        <p style="margin:0 0 12px;font-size:22px;font-weight:800;color:#0F172A;letter-spacing:1.5px">{order_code}</p>
        {f'<p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Pickup Location</p><p style="margin:0 0 16px;font-size:13px;color:#334155">{pickup_address}</p>' if pickup_address else ''}
        <hr style="border:none;border-top:1px solid #E2E8F0;margin:0 0 16px" />
        {_info_row(ICO_MAP_PIN, 'Please bring your order code when picking up')}
        {_info_row(ICO_CLOCK,   'Pick up your order at your earliest convenience')}
        {_info_row(ICO_PHONE,   'Contact us if you need assistance')}
      </div>

      <p style="margin:0;font-size:13px;color:#94A3B8;line-height:1.6">If you have any questions, reply to this email and we&#39;ll be happy to help.</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Your Order is Ready for Pickup — #{order_code}', 'html': _wrap(body, hero=_status_hero('ready_for_pickup'))})


def send_order_delivered_email(name: str, email: str, order_code: str, total: str = '', items: list | None = None, delivery_address: str = ''):
    items = items or []
    item_rows = _item_rows(items) if items else ''
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Order Delivered!</h2>
        <p style="margin:0;font-size:14px;color:#64748B">Hi <strong>{name}</strong>,</p>
      </div>

      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        Your order <strong>#{order_code}</strong> has been delivered!
      </p>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        We hope you enjoy your new purchase from Majo Gadgets.
      </p>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        Thank you for trusting us with your order. We truly appreciate your support and hope to see you again soon.
      </p>
      <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.7">
        Enjoy your new gadget!
      </p>

      <div style="padding:16px 20px;margin-bottom:24px">
        <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Order Code</p>
        <p style="margin:0 0 12px;font-size:22px;font-weight:800;color:#0F172A;letter-spacing:1.5px">{order_code}</p>
        <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Your Items</p>
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px">
          {item_rows}
          <tr>
            <td colspan="2" style="padding-top:12px;font-size:14px;font-weight:700;color:#0F172A">Total</td>
            <td style="padding-top:12px;font-size:15px;font-weight:800;color:#0F172A;text-align:right">{f'UGX {total}' if total else '—'}</td>
          </tr>
        </table>
      </div>

      <p style="margin:0 0 20px;font-size:15px;color:#475569;line-height:1.7">Enjoyed your experience? Please take a moment to rate your order — it helps us serve you better.</p>
      <div style="text-align:center">
        <a href="{settings.FRONTEND_URL}/rate/{order_code}" style="display:inline-block;padding:14px 32px;background:#071A2B !important;background-color:#071A2B !important;color:#ffffff !important;border:1px solid #071A2B;border-radius:0;font-weight:700;font-size:15px;text-decoration:none !important;line-height:1.4;vertical-align:middle">Rate Your Order</a>
      </div>
      <p style="margin:28px 0 0;font-size:13px;color:#94A3B8;line-height:1.6">— The Majo Gadgets Team</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Order Delivered — #{order_code}', 'html': _wrap(body, hero=_status_hero('delivered'))})


def send_product_rating_email(name: str, email: str, order_code: str, items: list):
    """
    items: list of dicts with keys: name, image, slug
    """
    item_blocks = ''
    for item in items:
        img_html = (
            f'<img src="{item["image"]}" width="56" height="56" alt="" style="border-radius:8px;object-fit:cover;display:block" />'
            if item.get('image') else
            f'<div style="width:56px;height:56px;background:#F1F5F9;border-radius:8px;text-align:center;line-height:56px">{_icon(ICO_PACKAGE, "#CBD5E1", 24)}</div>'
        )
        rate_url = f'{settings.FRONTEND_URL}/rate-product/{item["slug"]}?order_code={order_code}'
        item_blocks += f'''
        <tr>
          <td style="padding:12px 0;border-bottom:1px solid #F1F5F9;vertical-align:middle;width:68px">{img_html}</td>
          <td style="padding:12px 12px;border-bottom:1px solid #F1F5F9;vertical-align:middle">
            <p style="margin:0 0 6px;font-size:13px;font-weight:600;color:#0F172A">{item["name"]}</p>
            <div style="text-align:center"><a href="{rate_url}" style="display:inline-block;padding:6px 16px;background:#071A2B !important;background-color:#071A2B !important;color:#ffffff !important;border-radius:0;font-weight:700;font-size:12px;text-decoration:none !important">Rate Product</a></div>
          </td>
        </tr>'''

    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">How were your products?</h2>
        <p style="margin:0;font-size:14px;color:#64748B">Hi <strong>{name}</strong>, your order <strong>#{order_code}</strong> has been delivered!</p>
      </div>
      <p style="margin:0 0 20px;font-size:15px;color:#475569;line-height:1.7">
        We'd love to know what you think about the products you received. Your review helps other customers make better choices.
      </p>
      <div style="padding:16px 20px;margin-bottom:28px">
        <p style="margin:0 0 12px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Your Items</p>
        <table width="100%" cellpadding="0" cellspacing="0">
          {item_blocks}
        </table>
      </div>
      <p style="margin:0;font-size:13px;color:#94A3B8;line-height:1.6">Thank you for shopping with Majo Gadgets!</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Rate your products from order #{order_code}', 'html': _wrap(body)})


def send_order_rating_email(name: str, email: str, order_code: str, rating_url: str):
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Rate Your Experience</h2>
        <p style="margin:0;font-size:14px;color:#64748B">Hi <strong>{name}</strong>,</p>
      </div>

      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        We’d love to hear about your experience with Majo Gadgets.
      </p>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        Your order <strong>#{order_code}</strong> has been delivered, and we’d appreciate it if you could take a moment to rate the <strong>service and delivery experience</strong>.
      </p>
      <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.7">
        Your feedback helps us improve and provide an even better shopping experience for you and other customers.
      </p>

      <div style="text-align:center;margin-bottom:28px">
        <a href="{rating_url}" style="display:inline-block;padding:14px 40px;background:#071A2B !important;background-color:#071A2B !important;color:#ffffff !important;border:1px solid #071A2B;border-radius:0;font-weight:700;font-size:15px;text-decoration:none !important">
          Rate your experience
        </a>
      </div>

      <p style="margin:0 0 12px;font-size:15px;color:#475569;line-height:1.7">Thank you for shopping with Majo Gadgets!</p>
      <p style="margin:0;font-size:13px;color:#94A3B8;line-height:1.6">— The Majo Gadgets Team</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Rate Your Experience — #{order_code}', 'html': _wrap(body)})


def send_order_cancelled_email(name: str, email: str, order_code: str, reason: str):
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Order Cancelled</h2>
        <p style="margin:0;font-size:14px;color:#64748B">Hi <strong>{name}</strong>, your order <strong>#{order_code}</strong> has been cancelled.</p>
      </div>

      <div style="padding:16px 20px;margin-bottom:24px">
        <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Cancellation Reason</p>
        <p style="margin:0;font-size:14px;color:#334155;line-height:1.6">{reason}</p>
      </div>

      <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.7">If you believe this was a mistake or need further assistance, please don't hesitate to contact us.</p>
      <div style="text-align:center">
        <a href="{settings.FRONTEND_URL}" style="display:inline-block;padding:14px 32px;background:#071A2B !important;background-color:#071A2B !important;color:#ffffff !important;border:1px solid #071A2B;border-radius:0;font-weight:700;font-size:15px;text-decoration:none !important;line-height:1.4;vertical-align:middle">Continue Shopping &rarr;</a>
      </div>
      <p style="margin:28px 0 0;font-size:13px;color:#94A3B8;line-height:1.6">We hope to serve you again soon. Thank you for choosing Majo Gadgets.</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Order Cancelled — #{order_code}', 'html': _wrap(body)})


def send_password_reset_email(name: str, email: str, reset_url: str):
    body = f'''
      <div style="text-align:center;margin-bottom:28px">
        <h2 style="margin:0 0 8px;font-size:22px;color:#0F172A">Password Reset Request</h2>
        <p style="margin:0;font-size:14px;color:#64748B">We received a request to reset your password</p>
      </div>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        Hi <strong>{name}</strong>, no worries — it happens to the best of us! Click the button below to create a new password for your Majo Gadgets account.
      </p>
      <div style="padding:20px;margin-bottom:28px">
        <p style="margin:0 0 10px;font-size:12px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Security Notice</p>
        {_info_row(ICO_CLOCK, 'This link expires in <strong>1 hour</strong>', '#475569')}
        {_info_row(ICO_LOCK,  'For your security, this link can only be used once', '#475569')}
        {_info_row(ICO_MAIL,  'Only you should have access to this email', '#475569')}
      </div>
      <div style="text-align:center;margin-bottom:28px">
        <a href="{reset_url}" style="display:inline-block;padding:14px 40px;background:#071A2B !important;background-color:#071A2B !important;color:#ffffff !important;border:1px solid #071A2B;border-radius:0;font-weight:700;font-size:15px;text-decoration:none !important">
          Reset My Password &rarr;
        </a>
      </div>
      <p style="margin:0 0 8px;font-size:13px;color:#64748B;line-height:1.6">If the button doesn't work, copy and paste this link into your browser:</p>
      <p style="margin:0 0 24px;font-size:12px;color:#16A34A;word-break:break-all">{reset_url}</p>
      <p style="margin:0;font-size:13px;color:#94A3B8;line-height:1.6">If you didn't request a password reset, you can safely ignore this email.</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': 'Reset your Majo Gadgets password', 'html': _wrap(body)})


def send_password_changed_email(name: str, email: str):
    body = f'''
      <div style="text-align:center;margin-bottom:28px">
        <h2 style="margin:0 0 8px;font-size:22px;color:#0F172A">Password Changed</h2>
        <p style="margin:0;font-size:14px;color:#64748B">Your account password was successfully updated</p>
      </div>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        Hi <strong>{name}</strong>, this is a confirmation that the password for your Majo Gadgets account has just been changed.
      </p>
      <div style="padding:20px;margin-bottom:28px">
        <p style="margin:0 0 10px;font-size:12px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Security Notice</p>
        {_info_row(ICO_CHECK, 'Your password was changed successfully', '#475569')}
        {_info_row(ICO_LOCK,  'If you made this change, no further action is needed', '#475569')}
        {_info_row(ICO_MAIL,  'If you did not make this change, contact us immediately', '#DC2626')}
      </div>
      <p style="margin:0;font-size:13px;color:#94A3B8;line-height:1.6">If you did not change your password, please <a href="{settings.FRONTEND_URL}/forgot-password" style="color:#1E3A8A !important">reset it immediately</a>.</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': 'Your password has been changed', 'html': _wrap(body)})


def send_login_verification_email(name: str, email: str, code: str):
    body = f'''
      <div style="text-align:center;margin-bottom:28px">
        <h2 style="margin:0 0 8px;font-size:22px;color:#0F172A">Verify your sign-in</h2>
        <p style="margin:0;font-size:14px;color:#64748B">Secure access to your account</p>
      </div>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">Hi there,</p>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">We received a request to sign in to your <strong>Majo Gadgets</strong> account.</p>
      <p style="margin:0 0 20px;font-size:15px;color:#475569;line-height:1.7">To securely access your account, please enter the verification code below:</p>
      <p style="margin:0 0 10px;font-size:14px;font-weight:700;color:#0F172A">Your verification code</p>
      <table role="presentation" style="margin:0 0 8px;border-collapse:collapse">
        <tr>
          <td style="padding:16px 20px;background:#F1F5F9;font-size:30px;font-weight:800;letter-spacing:8px;color:#071A2B">{escape(code)}</td>
          <td aria-label="Select code to copy" style="padding:0 0 0 12px;color:#64748B;font-size:13px;white-space:nowrap">
            <span style="display:inline-block;width:10px;height:10px;border:1px solid #64748B;margin-right:-6px"></span><span style="display:inline-block;width:10px;height:10px;border:1px solid #64748B;background:#FFFFFF"></span>
            <span style="padding-left:4px">Select to copy</span>
          </td>
        </tr>
      </table>
      <p style="margin:0 0 24px;font-size:12px;color:#64748B">Select the code to copy it. On a phone, press and hold the code, then tap Copy.</p>
      <p style="margin:0 0 20px;font-size:13px;color:#475569;line-height:1.7">This code expires in <strong>10 minutes</strong> and can only be used once. For your security, never share this code with anyone, including anyone claiming to represent Majo Gadgets.</p>
      <p style="margin:0 0 8px;font-size:14px;font-weight:700;color:#0F172A">Didn't request this code?</p>
      <p style="margin:0 0 20px;font-size:13px;color:#475569;line-height:1.7">If you didn't attempt to sign in, you can safely ignore this email. Your account remains secure unless someone has access to your login credentials. If you suspect unauthorized activity, we recommend changing your password.</p>
      <p style="margin:0 0 16px;font-size:13px;color:#475569;line-height:1.7">Thank you for choosing Majo Gadgets. We're committed to keeping your account safe and your shopping experience secure.</p>
      <p style="margin:0;font-size:13px;color:#475569;line-height:1.7">Best regards,<br><strong>The Majo Gadgets Team</strong><br><em>Quality gadgets, great value.</em></p>
    '''
    _send({'from': FROM, 'to': email, 'subject': 'Your Majo Gadgets sign-in code', 'html': _wrap(body)})


def send_payment_successful_email(name: str, email: str, order_code: str, total: str, items: list, payment_method: str = ''):
    method_line = f'<p style="margin:0 0 12px;font-size:13px;color:#334155"><strong>Payment method:</strong> {payment_method}</p>' if payment_method else ''
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Payment Received!</h2>
        <p style="margin:0;font-size:14px;color:#64748B">Hi <strong>{name}</strong>, your payment was successful.</p>
      </div>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        We've received your payment for order <strong>#{order_code}</strong>. Your order is now confirmed and being prepared.
      </p>
      <div style="padding:16px 20px;margin-bottom:24px">
        <p style="margin:0 0 2px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Order Code</p>
        <p style="margin:0 0 12px;font-size:22px;font-weight:800;color:#0F172A;letter-spacing:1.5px">{order_code}</p>
        {method_line}
        <hr style="border:none;border-top:1px solid #E2E8F0;margin:0 0 16px" />
        <p style="margin:0 0 12px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Items</p>
        <table width="100%" cellpadding="0" cellspacing="0">
          {_item_rows(items)}
          <tr>
            <td colspan="2" style="padding-top:12px;font-size:14px;font-weight:700;color:#0F172A">Total Paid</td>
            <td style="padding-top:12px;font-size:15px;font-weight:800;color:#16A34A;text-align:right">UGX {total}</td>
          </tr>
        </table>
      </div>
      <div style="text-align:center">
        <a href="{settings.FRONTEND_URL}/orders/{order_code}" style="display:inline-block;padding:14px 32px;background:#071A2B !important;background-color:#071A2B !important;color:#ffffff !important;border:1px solid #071A2B;border-radius:0;font-weight:700;font-size:15px;text-decoration:none !important">
          Track Your Order &rarr;
        </a>
      </div>
      <p style="margin:28px 0 0;font-size:13px;color:#94A3B8">Thank you for shopping with Majo Gadgets!</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Payment Confirmed — Order #{order_code}', 'html': _wrap(body, hero=_status_hero('processing'))})


def send_payment_failed_email(name: str, email: str, order_code: str, total: str, reason: str = 'failed'):
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Payment Unsuccessful</h2>
        <p style="margin:0;font-size:14px;color:#64748B">Hi <strong>{name}</strong>, your payment for order <strong>#{order_code}</strong> did not go through.</p>
      </div>
      <div style="padding:16px 20px;margin-bottom:24px">
        <p style="margin:0 0 4px;font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.5px">Reason</p>
        <p style="margin:0;font-size:14px;color:#DC2626;font-weight:600">Payment {reason}</p>
      </div>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        Your order has been cancelled. No money has been deducted from your account.
      </p>
      <p style="margin:0 0 24px;font-size:15px;color:#475569;line-height:1.7">
        You can place a new order and try again. If you keep experiencing issues, please contact us.
      </p>
      <div style="text-align:center">
        <a href="{settings.FRONTEND_URL}/shop" style="display:inline-block;padding:14px 32px;background:#071A2B !important;background-color:#071A2B !important;color:#ffffff !important;border:1px solid #071A2B;border-radius:0;font-weight:700;font-size:15px;text-decoration:none !important">
          Shop Again &rarr;
        </a>
      </div>
      <p style="margin:28px 0 0;font-size:13px;color:#94A3B8">Need help? Reply to this email and we'll sort it out.</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Payment Failed — Order #{order_code}', 'html': _wrap(body)})


def send_return_approved_email(email: str, order_code: str):
    safe_order_code = escape(order_code)
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Your Return Request Has Been Approved!</h2>
      </div>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        Hi there!
      </p>
      <p style="margin:0 0 16px;font-size:13px;color:#64748B;line-height:1.7">
        Good news! Your return request for order <strong>#{safe_order_code}</strong> has been reviewed and approved. We’ll guide you through the next steps to ensure your return process is as smooth and convenient as possible.
      </p>
      <p style="margin:0 0 16px;font-size:13px;color:#64748B;line-height:1.7">Thank you for your patience and for giving us the opportunity to make things right. We truly appreciate your trust in Majo Gadgets!</p>
      <p style="margin:24px 0 0;font-size:14px;color:#334155;font-weight:700">Thank you for choosing Majo Gadgets — your next great upgrade awaits!</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Return Request Approved — Order #{safe_order_code}', 'html': _wrap(body)})


def send_refund_processed_email(email: str, order_code: str):
    safe_order_code = escape(order_code)
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Your Refund Has Been Successfully Processed!</h2>
      </div>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">Hi there!</p>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">Good news! Your refund for order <strong>#{safe_order_code}</strong> has been processed and will be sent back through the same payment method you used when placing your order.</p>
      <p style="margin:20px 0 8px;font-size:15px;color:#334155;font-weight:700">When will you receive your money?</p>
      <ul style="margin:0 0 16px;padding-left:22px;font-size:14px;color:#475569;line-height:1.8">
        <li><strong>Mobile Money:</strong> Please allow 1–3 business days for the refund to reflect in your account.</li>
        <li><strong>Card Payments:</strong> Please allow 4–7 business days for the refund to reflect in your account.</li>
      </ul>
      <p style="margin:0 0 16px;font-size:13px;color:#64748B;line-height:1.7">Please note that the actual time may depend on your payment provider. Weekends and public holidays are not counted as business days.</p>
      <p style="margin:0 0 16px;font-size:13px;color:#64748B;line-height:1.7">Thank you for your patience and understanding. We’re sorry things didn’t work out as expected, and we appreciate the opportunity to serve you.</p>
      <p style="margin:0 0 16px;font-size:13px;color:#64748B;line-height:1.7">We hope to welcome you back to Majo Gadgets soon for an even better shopping experience!</p>
      <p style="margin:24px 0 0;font-size:14px;color:#334155;font-weight:700">Majo Gadgets — your next great upgrade awaits!</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Refund Processed — Order #{safe_order_code}', 'html': _wrap(body)})


def send_trader_approved_email(name: str, email: str, business_name: str, trader_uuid: str):
    portal_url = f'{settings.FRONTEND_URL}/trader/{trader_uuid}'
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#0F172A">Congratulations, {name}!</h2>
        <p style="margin:0;font-size:14px;color:#64748B">Your trader application has been approved</p>
      </div>
      <p style="margin:0 0 16px;font-size:15px;color:#475569;line-height:1.7">
        We're excited to welcome <strong>{business_name}</strong> to the Majo Gadgets platform!
        Your application has been reviewed and approved by our team.
      </p>
      <ul style="margin:0 0 28px;padding-left:22px;list-style:disc">
        {_bullet_row('List and sell your products on Majo Gadgets')}
        {_bullet_row('Track your sales and revenue in real time')}
        {_bullet_row('Manage your trader account from your portal')}
      </ul>
      <div style="text-align:center">
        <a href="{portal_url}" style="display:inline-block;padding:14px 32px;background:#071A2B !important;background-color:#071A2B !important;color:#ffffff !important;border:1px solid #071A2B;border-radius:0;font-weight:700;font-size:15px;text-decoration:none !important">
          Open My Trader Portal &rarr;
        </a>
      </div>
      <p style="margin:28px 0 0;font-size:13px;color:#94A3B8">If you have any questions, just reply to this email — we're always happy to help.</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Your Trader Application is Approved — {business_name}', 'html': _wrap(body)})


def send_trader_agreement_email(name: str, email: str, business_name: str, agreement_url: str, reference: str, version: str):
    body = f'''
      <div style="text-align:center;margin-bottom:24px">
        <h2 style="margin:0 0 6px;font-size:22px;color:#111111">Your trader agreement is ready</h2>
        <p style="margin:0;font-size:14px;color:#333333">Hello {escape(name)}, your application for {escape(business_name)} has been approved.</p>
      </div>
      <p style="font-size:14px;line-height:1.7;color:#334155">Review the agreement, confirm your legal name, and sign electronically to activate selling. You may sign by typing your verified name, with an optional signature image.</p>
      <p style="font-size:13px;color:#334155"><strong>Reference:</strong> {escape(reference)}<br><strong>Version:</strong> {escape(version)}</p>
      <div style="text-align:center;margin:24px 0">
        <a href="{escape(agreement_url, quote=True)}" style="display:inline-block;padding:14px 32px;background:#071A2B !important;color:#ffffff !important;font-weight:700;text-decoration:none !important">Review and sign agreement</a>
      </div>
      <p style="font-size:12px;line-height:1.6;color:#64748B">Your National ID copy is retained for private verification and is not included in the agreement.</p>
    '''
    _send({'from': FROM, 'to': email, 'subject': f'Trader Agreement Ready — {reference}', 'html': _wrap(body)})
