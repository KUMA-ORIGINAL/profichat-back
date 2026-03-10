from datetime import timedelta

from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken


def should_use_short_token_lifetime(user_id):
    short_lived_user_ids = getattr(settings, "TEST_SHORT_TOKEN_USER_IDS", set())
    return int(user_id) in set(short_lived_user_ids)


def get_short_access_token_lifetime():
    seconds = int(getattr(settings, "TEST_SHORT_ACCESS_TOKEN_LIFETIME_SECONDS", 60))
    return timedelta(seconds=seconds)


def get_short_refresh_token_lifetime():
    seconds = int(getattr(settings, "TEST_SHORT_REFRESH_TOKEN_LIFETIME_SECONDS", 300))
    return timedelta(seconds=seconds)


def build_refresh_for_user(user):
    refresh = RefreshToken.for_user(user)
    if should_use_short_token_lifetime(user.id):
        refresh.set_exp(lifetime=get_short_refresh_token_lifetime())
        refresh.access_token.set_exp(lifetime=get_short_access_token_lifetime())
    return refresh
