"""Тонкий клиент Centrifugo: HTTP API (broadcast, batch presence_stats) и выпуск JWT для клиентов."""
from datetime import datetime, timedelta, timezone as dt_timezone

import jwt
import requests
from django.conf import settings

API_TIMEOUT = 3  # секунд
PRESENCE_TIMEOUT = 1  # секунд: presence нужен для списка чатов, ждать дольше нельзя
CONNECTION_TOKEN_TTL = timedelta(hours=1)
SUBSCRIPTION_TOKEN_TTL = timedelta(hours=1)


class CentrifugoError(Exception):
    """Centrifugo недоступен, отклонил запрос или не настроен."""


def _secret() -> str:
    secret = settings.CENTRIFUGO_TOKEN_SECRET
    if not secret:
        raise CentrifugoError("CENTRIFUGO_TOKEN_SECRET не задан")
    return secret


def _api_call(method: str, payload: dict, timeout) -> dict | None:
    """POST {CENTRIFUGO_API_URL}/<method>; тело ответа (dict) или None, если ответ не JSON."""
    base_url = settings.CENTRIFUGO_API_URL
    if not base_url:
        raise CentrifugoError("CENTRIFUGO_API_URL не задан")
    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/{method}",
            headers={"X-API-Key": settings.CENTRIFUGO_API_KEY},
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise CentrifugoError(f"Centrifugo недоступен: {exc}") from exc

    if not 200 <= response.status_code < 300:
        raise CentrifugoError(f"Centrifugo ответил {response.status_code}: {response.text[:200]}")

    # Ошибки уровня API Centrifugo приходят с кодом 200 и полем error в теле
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict) and body.get("error"):
        raise CentrifugoError(f"Centrifugo вернул ошибку: {body['error']}")
    return body if isinstance(body, dict) else None


def broadcast(channels, data):
    """Публикует `data` одновременно в несколько каналов (HTTP API v6: /api/broadcast)."""
    _api_call("broadcast", {"channels": list(channels), "data": data}, API_TIMEOUT)


def presence_stats_batch(channels) -> dict[str, int | None]:
    """
    Число пользователей в presence каждого канала — ОДНИМ запросом (HTTP API v6: /api/batch,
    команда `presence_stats` на канал, `parallel: true`).

    Ответ: {channel: num_users}; None — Centrifugo вернул ошибку для этого канала.
    Короткий таймаут: вызывается при выдаче списка чатов. Ошибка запроса → CentrifugoError.
    """
    channels = list(channels)
    if not channels:
        return {}
    body = _api_call(
        "batch",
        {"commands": [{"presence_stats": {"channel": channel}} for channel in channels], "parallel": True},
        PRESENCE_TIMEOUT,
    )
    replies = (body or {}).get("replies") or []
    result = {}
    for index, channel in enumerate(channels):
        reply = replies[index] if index < len(replies) and isinstance(replies[index], dict) else {}
        stats = reply.get("presence_stats")
        if reply.get("error") or not isinstance(stats, dict):
            result[channel] = None
        else:
            # нулевые поля Centrifugo может опускать
            result[channel] = int(stats.get("num_users") or 0)
    return result


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
