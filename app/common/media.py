from django.conf import settings
from rest_framework import serializers


def absolute_media_url(file) -> str | None:
    """
    Абсолютный URL файла (`https://<DOMAIN>/media/...`) без request — для событий, пушей и
    ответов, где ссылка должна быть одинаковой. None, если файла нет. Уже абсолютный URL
    хранилища (S3 и т. п.) возвращается как есть.
    """
    if not file:
        return None
    url = file.url
    if url.startswith(("http://", "https://")):
        return url
    return f"https://{settings.DOMAIN}{url}"


class AbsoluteImageField(serializers.ImageField):
    """ImageField только для чтения: всегда абсолютный URL через `absolute_media_url`, есть ли request или нет."""

    def __init__(self, **kwargs):
        kwargs.setdefault("read_only", True)
        super().__init__(**kwargs)

    def to_representation(self, value):
        return absolute_media_url(value)
