from django.db import models
from django.utils import timezone
from datetime import timedelta

from phonenumber_field.modelfields import PhoneNumberField


class OTP(models.Model):
    CHANNEL_WHATSAPP = "whatsapp"
    CHANNEL_SMS = "sms"
    CHANNEL_CHOICES = (
        (CHANNEL_WHATSAPP, "WhatsApp"),
        (CHANNEL_SMS, "SMS"),
    )
    SCENARIO_BY_CHANNEL = {
        CHANNEL_WHATSAPP: "otp",
        CHANNEL_SMS: "otp_sms",
    }

    phone_number = PhoneNumberField("phone number")
    code = models.CharField(max_length=6)
    channel = models.CharField(
        "канал последней отправки",
        max_length=16,
        choices=CHANNEL_CHOICES,
        default=CHANNEL_WHATSAPP,
    )
    sms_resent_at = models.DateTimeField("повторно отправлен по SMS", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=5)

    def __str__(self):
        return f"{self.phone_number} - {self.code}"
