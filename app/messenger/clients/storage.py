"""Тонкий клиент MinIO/S3: presigned-ссылки (подпись на публичном хосте) и операции с объектами (внутренний хост)."""
import re
from functools import lru_cache
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings

MAX_SAFE_NAME_LENGTH = 100
_UNSAFE_CHARS = re.compile(r"[^\w.\-]+", re.UNICODE)


@lru_cache(maxsize=8)
def _build_client(endpoint_url, access_key, secret_key, region):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url or None,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _client(endpoint_url):
    return _build_client(endpoint_url, settings.S3_ACCESS_KEY, settings.S3_SECRET_KEY, settings.S3_REGION)


def _internal_client():
    return _client(settings.S3_ENDPOINT_URL)


def _public_client():
    # подпись считается на внешний хост, иначе Host-заголовок не совпадёт и MinIO отклонит запрос
    return _client(settings.S3_PUBLIC_ENDPOINT_URL or settings.S3_ENDPOINT_URL)


def safe_file_name(file_name: str) -> str:
    """Имя файла для ключа объекта: без путей и спецсимволов, не длиннее 100 символов (расширение сохраняется)."""
    name = (file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_CHARS.sub("_", name).strip("._")
    if not name:
        return "file"
    if len(name) > MAX_SAFE_NAME_LENGTH:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            name = stem[: MAX_SAFE_NAME_LENGTH - len(ext) - 1] + "." + ext
        else:
            name = name[:MAX_SAFE_NAME_LENGTH]
    return name


def presigned_put(key: str, content_type: str, expires: int) -> str:
    """Ссылка для загрузки объекта методом PUT; клиент обязан передать тот же Content-Type."""
    return _public_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
    )


def presigned_get(key: str, expires: int, file_name: str) -> str:
    """Ссылка для скачивания с именем файла в Content-Disposition."""
    disposition = "attachment; filename*=UTF-8''" + quote(file_name or "file", safe="")
    return _public_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.S3_BUCKET,
            "Key": key,
            "ResponseContentDisposition": disposition,
        },
        ExpiresIn=expires,
    )


def head(key: str) -> dict | None:
    """Метаданные объекта (`ContentLength`, ...) или None, если объекта нет."""
    try:
        return _internal_client().head_object(Bucket=settings.S3_BUCKET, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def put_stream(key: str, fileobj, content_type: str) -> None:
    """Загрузка потока с сервера (например, при импорте истории)."""
    _internal_client().upload_fileobj(
        fileobj, settings.S3_BUCKET, key, ExtraArgs={"ContentType": content_type}
    )


def delete(key: str) -> None:
    _internal_client().delete_object(Bucket=settings.S3_BUCKET, Key=key)
