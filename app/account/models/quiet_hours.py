from django.db import models

from common.models import BaseModel


class QuietHoursState(BaseModel):
    """Тихие часы специалиста: в нерабочее время пуши чата выключены в Stream.

    Строка есть, пока тишина действует. `quiet_since` — с какого момента
    считать пропущенное для утренней сводки, `muted_until` — до какого
    момента пуши выключены в Stream (начало следующей смены).
    """

    user = models.OneToOneField(
        "User",
        on_delete=models.CASCADE,
        related_name="quiet_hours",
        verbose_name="Специалист",
    )
    quiet_since = models.DateTimeField("Тишина с")
    muted_until = models.DateTimeField("Пуши выключены до")

    class Meta:
        verbose_name = "Тихие часы"
        verbose_name_plural = "Тихие часы"

    def __str__(self):
        return f"QuietHoursState<user={self.user_id} until={self.muted_until}>"
