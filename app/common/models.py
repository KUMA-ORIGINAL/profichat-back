from django.db import models


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата последнего обновления")

    class Meta:
        abstract = True
        verbose_name = "Базовая модель"
        verbose_name_plural = "Базовые модели"

    def __str__(self):
        return f"Модель {self.__class__.__name__} (ID: {self.pk})"
