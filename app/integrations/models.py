import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class SSOLoginToken(models.Model):
    PARTNER_MEDCRM = "medcrm"

    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sso_login_tokens",
    )
    partner = models.CharField(max_length=100, default=PARTNER_MEDCRM)
    next_path = models.CharField(max_length=512, default="/")
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["partner", "token_hash"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["expires_at"]),
        ]

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode()).hexdigest()

    @classmethod
    def create_for_user(cls, user, next_path="/"):
        raw_token = secrets.token_urlsafe(48)
        ttl_seconds = int(
            getattr(
                settings,
                "MEDCRM_SSO_TTL_SECONDS",
                getattr(settings, "SECOND_SYSTEM_SSO_TTL_SECONDS", 120),
            )
        )
        cls.objects.create(
            token_hash=cls.hash_token(raw_token),
            user=user,
            partner=cls.PARTNER_MEDCRM,
            next_path=next_path or "/",
            expires_at=timezone.now() + timedelta(seconds=ttl_seconds),
        )
        return raw_token

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now()
