from django.db import models
from django.utils import timezone
from datetime import timedelta

from phonenumber_field.modelfields import PhoneNumberField


class OTP(models.Model):
    phone_number = PhoneNumberField("phone number")
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=5)

    def __str__(self):
        return f"{self.phone_number} - {self.code}"
