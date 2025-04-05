from datetime import timedelta
from pathlib import Path

import environ
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False)
)

SECRET_KEY = env('SECRET_KEY')

DEBUG = bool(env("DEBUG", default=0))

ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS").split(" ")

DOMAIN = env("DOMAIN")

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_HEADERS = ["Authorization", "Content-Type", "Accept"]

if DEBUG:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
else:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True


INSTALLED_APPS = [
    'modeltranslation',
    'unfold',
    "unfold.contrib.filters",
    "unfold.contrib.forms",

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    "django.contrib.postgres",

    'rest_framework',
    'drf_spectacular',
    'django_filters',
    'corsheaders',
    'cachalot',

    'account',
    'common',
    'chat_access'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',

    'corsheaders.middleware.CorsMiddleware',
    'djangorestframework_camel_case.middleware.CamelCaseMiddleWare',
    'config.middleware.LanguageMiddleware',

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
        'DIRS': [
            BASE_DIR / 'templates',
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('POSTGRES_DB'),
        'USER': env('POSTGRES_USER'),
        'PASSWORD': env('POSTGRES_PASSWORD'),
        'HOST': env('POSTGRES_HOST'),
        'PORT': env('POSTGRES_PORT'),
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


LANGUAGE_CODE = 'ru'

TIME_ZONE = 'Asia/Bishkek'

USE_I18N = True

USE_TZ = True


STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'static'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

STREAM_API_KEY=env("STREAM_API_KEY")
STREAM_API_SECRET=env("STREAM_API_SECRET")

SMS_LOGIN=env("SMS_LOGIN")
SMS_PASSWORD=env("SMS_PASSWORD")

LANGUAGES = (
    ('ru', 'Russian'),
    ('en', 'English'),
    ('ky', 'Kyrgyz'),
)

MODELTRANSLATION_DEFAULT_LANGUAGE = 'ru'
MODELTRANSLATION_LANGUAGES = ('ru', 'en', 'ky')
MODELTRANSLATION_FALLBACK_LANGUAGES = {
    'default': ('ru',),
    'en': ('ru', 'ky'),  # Для английского fallback на русский и кыргызский
    'ky': ('ru',),  # Для кыргызского fallback на русский
}
MODELTRANSLATION_AUTO_POPULATE = True


EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

CSRF_TRUSTED_ORIGINS = [f"https://{DOMAIN}", f"http://{DOMAIN}"]

AUTH_USER_MODEL = 'account.User'

# CACHES = {
#     'default': {
#         'BACKEND': 'django_redis.cache.RedisCache',
#         'LOCATION': 'redis://redis:6379/1',
#         'OPTIONS': {
#             'CLIENT_CLASS': 'django_redis.client.DefaultClient',
#         }
#     }
# }

# CACHALOTE_ONLY_CACHABLE_MODELS = (
#     'menu.category',          # Кешировать только эти модели
#     'menu.product',  # Кешировать только эти модели
#     'menu.modificator',  # Кешировать только эти модели
# )
# CACHALOT_TIMEOUT = 60 * 30
#
# CHANNEL_LAYERS = {
#     'default': {
#         'BACKEND': 'channels_redis.core.RedisChannelLayer',
#         'CONFIG': {
#             "hosts": ['redis://redis:6379/2'],  # Используем другой слот Redis (например, /2)
#         },
#     },
# }


SPECTACULAR_SETTINGS = {
    'TITLE': 'ProfiChat',
    'DESCRIPTION': 'Your project description',
    'VERSION': '1.0.0',
    'SCHEMA_VERSION': '3.1.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'CAMELIZE_NAMES': True,

    'POSTPROCESSING_HOOKS': [
        'drf_spectacular.contrib.djangorestframework_camel_case.camelize_serializer_fields',
    ],

    'SERVE_PUBLIC': True,
    'SERVE_HTTPS': True,
}

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_RENDERER_CLASSES': (
        'djangorestframework_camel_case.render.CamelCaseJSONRenderer',
        'djangorestframework_camel_case.render.CamelCaseBrowsableAPIRenderer',
    ),
    'DEFAULT_PARSER_CLASSES': (
        'djangorestframework_camel_case.parser.CamelCaseFormParser',
        'djangorestframework_camel_case.parser.CamelCaseMultiPartParser',
        'djangorestframework_camel_case.parser.CamelCaseJSONParser',
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "AUTH_HEADER_TYPES": ("Bearer",),
    'UPDATE_LAST_LOGIN': True,
}

DJOSER = {
    # 'SERIALIZERS': {
    #     'user': 'account.serializers.UserSerializer',
    #     'current_user': 'account.serializers.UserSerializer',
    # },
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} - {asctime} - {module} - {name} - {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} - {module} - {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',  # Можно изменить на 'DEBUG' для более подробного вывода
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file': {
            'level': 'INFO',  # Логи с уровнем DEBUG и выше будут записываться в файл
            'class': 'logging.FileHandler',
            'filename': 'django_app.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        # 'django.db.backends': {
        #     'level': 'DEBUG',
        #     'handlers': ['console'],
        # },
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}

UNFOLD = {
    "SITE_TITLE": 'ProfiChat',
    "SITE_HEADER": "ProfiChat",
    "SITE_URL": "/",
    "SITE_SYMBOL": "settings",  # symbol from icon set
    "SHOW_HISTORY": True, # show/hide "History" button, default: True
    "SHOW_VIEW_ON_SITE": True, # show/hide "View on site" button, default: True
    "BORDER_RADIUS": "6px",
    "COLORS": {
        "base": {
            "50": "249 250 251",
            "100": "243 244 246",
            "200": "229 231 235",
            "300": "209 213 219",
            "400": "156 163 175",
            "500": "107 114 128",
            "600": "75 85 99",
            "700": "55 65 81",
            "800": "31 41 55",
            "900": "17 24 39",
            "950": "3 7 18",
        },
        "primary": {
            "50": "250 245 255",
            "100": "243 232 255",
            "200": "233 213 255",
            "300": "216 180 254",
            "400": "192 132 252",
            "500": "168 85 247",
            "600": "147 51 234",
            "700": "126 34 206",
            "800": "107 33 168",
            "900": "88 28 135",
            "950": "59 7 100",
        },
        "font": {
            "subtle-light": "var(--color-base-500)",  # text-base-500
            "subtle-dark": "var(--color-base-400)",  # text-base-400
            "default-light": "var(--color-base-600)",  # text-base-600
            "default-dark": "var(--color-base-300)",  # text-base-300
            "important-light": "var(--color-base-900)",  # text-base-900
            "important-dark": "var(--color-base-100)",  # text-base-100
        },
    },
    "SIDEBAR": {
        "show_search": False,  # Search in applications and models names
        "show_all_applications": False,  # Dropdown with all applications and models
        "navigation": [
            # {
            #     "title": _("Навигация"),
            #     "items": [
            #         {
            #             "title": _("Организация"),
            #             "icon": "corporate_fare",
            #             "link": reverse_lazy("admin:organizations_organization_changelist"),
            #             'permission': 'account.admin_permissions.permission_callback_for_doctor_and_accountant',
            #         },
            #         {
            #             "title": _("Здания"),
            #             "icon": "location_city",
            #             "link": reverse_lazy("admin:organizations_building_changelist"),
            #             'permission': 'account.admin_permissions.permission_callback_for_doctor_and_accountant',
            #         },
            #         {
            #             "title": _("Отделы"),
            #             "icon": "account_tree",
            #             "link": reverse_lazy("admin:organizations_department_changelist"),
            #             'permission': 'account.admin_permissions.permission_callback_for_doctor_and_accountant',
            #         },
            #         {
            #             "title": _("Кабинеты"),
            #             "icon": "meeting_room",
            #             "link": reverse_lazy("admin:organizations_room_changelist"),
            #             'permission': 'account.admin_permissions.permission_callback_for_doctor_and_accountant',
            #         },
            #     ],
            # },
            # {
            #     "title": _("Услуги"),
            #     "separator": True,
            #     "items": [
            #         {
            #             "title": _("Услуги"),
            #             "icon": "construction",
            #             "link": reverse_lazy("admin:services_service_changelist"),
            #             'permission': 'account.admin_permissions.permission_callback_for_doctor_and_accountant',
            #         },
            #     ],
            # },
            {
                "title": _("Навигация"),
                "items": [
                    {
                        "title": _("Категории специальностей"),
                        "icon": "category",
                        "link": reverse_lazy("admin:account_professioncategory_changelist"),
                    },
                    {
                        "title": _("Заявки на бизнес"),
                        "icon": "contact_mail",
                        "link": reverse_lazy("admin:account_application_changelist"),
                    },
                    {
                        "title": _("Тарифы"),
                        "icon": "paid",  # иконка от Material Icons, можно заменить
                        "link": reverse_lazy("admin:chat_access_tariff_changelist"),
                    },
                    {
                        "title": _("Заказы доступа"),
                        "icon": "assignment",  # тоже иконка от Material Icons
                        "link": reverse_lazy("admin:chat_access_accessorder_changelist"),
                    },
                ],
            },
            {
                "title": _("Пользователи"),
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": _("Пользователи"),
                        "icon": "person",
                        "link": reverse_lazy("admin:account_user_changelist"),
                    },
                ],
            },
            {
                "title": _("Группы"),
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": _("Группы"),
                        "icon": "group",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                    },
                ],
            },
        ],
    },
    # "TABS": [
    #     {
    #         "models": ["venues.venue"],
    #         "items": [
    #             {
    #                 "title": "Генерация qr-code",
    #                 "icon": "grade",
    #                 "link": reverse_lazy("admin:qr"),
    #             },
    #         ],
    #     },
    # ],
}