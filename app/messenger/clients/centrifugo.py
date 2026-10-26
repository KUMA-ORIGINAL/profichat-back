"""Тонкий клиент Centrifugo: HTTP API (broadcast) и выпуск JWT для клиентов."""
from datetime import datetime, timedelta, timezone as dt_timezone

import jwt
import requests
from django.conf import settings

API_TIMEOUT = 3  # секунд
CONNECTION_TOKEN_TTL = timedelta(hours=1)
SUBSCRIPTION_TOKEN_TTL = timedelta(hours=1)


class CentrifugoError(Exception):
    """Centrifugo недоступен, отклонил запрос или не настроен."""


def _secret() -> str:
    secret = settings.CENTRIFUGO_TOKEN_SECRET
    if not secret:
        raise CentrifugoError("CENTRIFUGO_TOKEN_SECRET не задан")
    return secret


def broadcast(channels, data):
    """Публикует `data` одновременно в несколько каналов (HTTP API v6: /api/broadcast)."""
    base_url = settings.CENTRIFUGO_API_URL
    if not base_url:
        raise CentrifugoError("CENTRIFUGO_API_URL не задан")
    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/broadcast",
            headers={"X-API-Key": settings.CENTRIFUGO_API_KEY},
            json={"channels": list(channels), "data": data},
            timeout=API_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise CentrifugoError(f"Centrifugo недоступен: {exc}") from exc

    if not 200 <= response.status_code < 300:
        raise CentrifugoError(f"Centrifugo ответил {response.status_code}: {response.text[:200]}")

    # Ошибки уровня API Centrifugo приходят с кодом 200 и полем error в теле
    try:
        body = response.json()
    except ValueError:
        return
    if isinstance(body, dict) and body.get("error"):
        raise CentrifugoError(f"Centrifugo вернул ошибку: {body['error']}")


def connection_token(user_id: int) -> tuple[str, datetime]:
    """Токен подключения; личный канал подписывается на стороне сервера (claim `channels`)."""
    expires_at = datetime.now(dt_timezone.utc) + CONNECTION_TOKEN_TTL
    token = jwt.encode(
        {"sub": str(user_id), "exp": expires_at, "channels": [f"personal:{user_id}"]},
        _secret(),
        algorithm="HS256",
    )
    return token, expires_at


def subscription_token(user_id: int, channel: str) -> str:
    """Токен подписки на канал `channel` (namespace `chat` требует его)."""
    expires_at = datetime.now(dt_timezone.utc) + SUBSCRIPTION_TOKEN_TTL
    return jwt.encode(
        {"sub": str(user_id), "channel": channel, "exp": expires_at},
        _secret(),
        algorithm="HS256",
    )
