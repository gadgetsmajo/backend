from pathlib import Path
from datetime import timedelta
from decouple import config
import dj_database_url
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DJANGO_DEBUG', default=False, cast=bool) and not os.environ.get('RAILWAY_ENVIRONMENT')
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin-allow-popups'
_configured_allowed_hosts = config('ALLOWED_HOSTS', default='').split(',')
ALLOWED_HOSTS = [
    host.strip()
    for host in (
        *_configured_allowed_hosts,
        'web-production-b3675.up.railway.app',
        'api.majogadgets.com',
        *(['*', '.ngrok-free.app', '.ngrok-free.dev'] if DEBUG else []),
    )
    if host.strip()
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # third party
    'rest_framework',
    'corsheaders',
    # local
    'users',
    'products',
    'orders',
    'settings_app',
    'inventory',
    'accounting',
    'traders',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASE_URL = os.environ.get('DATABASE_URL', '')
DATABASES = {
    'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600)
    if DATABASE_URL else
    {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

import cloudinary
cloudinary.config(
    cloud_name=config('CLOUDINARY_CLOUD_NAME'),
    api_key=config('CLOUDINARY_API_KEY'),
    api_secret=config('CLOUDINARY_API_SECRET'),
    secure=True,
)

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'users.User'

_configured_cors_origins = config('CORS_ALLOWED_ORIGINS', default='').split(',')
CORS_ALLOWED_ORIGINS = [
    origin.strip().rstrip('/')
    for origin in (
        *_configured_cors_origins,
        'https://majogadgets.com',
        'https://www.majogadgets.com',
    )
    if origin.strip()
]
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOW_HEADERS = [
    'accept', 'accept-encoding', 'authorization', 'content-type',
    'dnt', 'origin', 'user-agent', 'x-csrftoken', 'x-requested-with',
    'ngrok-skip-browser-warning',
]
CORS_PREFLIGHT_MAX_AGE = 86400

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'users.authentication.MfaJWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'TOKEN_REFRESH_SERIALIZER': 'users.authentication.MfaTokenRefreshSerializer',
}

# Cache
REDIS_URL = os.environ.get('REDIS_URL', '')
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
    } if REDIS_URL else {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# Logging — captures payment security events
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'loggers': {
        'orders': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

GOOGLE_CLIENT_ID = config('GOOGLE_CLIENT_ID', default='')

# Resend email
RESEND_API_KEY = config('RESEND_API_KEY', default='')
FRONTEND_URL = config('FRONTEND_URL', default='https://www.majogadgets.com')
ADMIN_EMAIL = config('ADMIN_EMAIL', default='admin@majogadgets.com')
SUPPORT_EMAIL = config('SUPPORT_EMAIL', default='support@majogadgets.com')
MAJO_LEGAL_OPERATOR_NAME = config('MAJO_LEGAL_OPERATOR_NAME', default='Walunsimbi John')
MAJO_LEGAL_OPERATOR_TITLE = config('MAJO_LEGAL_OPERATOR_TITLE', default='CEO')
MAJO_BUSINESS_ADDRESS = config('MAJO_BUSINESS_ADDRESS', default='')

# TextBee SMS
TEXTBEE_API_KEY = config('TEXTBEE_API_KEY', default='')
TEXTBEE_DEVICE_ID = config('TEXTBEE_DEVICE_ID', default='')

# Pesapal
PESAPAL_CONSUMER_KEY = config('PESAPAL_CONSUMER_KEY', default='')
PESAPAL_CONSUMER_SECRET = config('PESAPAL_CONSUMER_SECRET', default='')
PESAPAL_BASE_URL = config('PESAPAL_BASE_URL', default='https://cybqa.pesapal.com/pesapalv3')  # sandbox default
PESAPAL_REFUND_USERNAME = config('PESAPAL_REFUND_USERNAME', default='')
PESAPAL_IPN_URL = config('PESAPAL_IPN_URL', default='')
PESAPAL_CALLBACK_URL = config('PESAPAL_CALLBACK_URL', default='')

# Celery
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
