"""Тонкий клиент LiveKit: комнаты (Room Service API), токены участников и проверка вебхуков."""
import asyncio
from datetime import timedelta

import aiohttp
from django.conf import settings
from google.protobuf.json_format import MessageToDict
from livekit import api

TOKEN_TTL = timedelta(hours=2)
ROOM_MAX_PARTICIPANTS = 2
ROOM_EMPTY_TIMEOUT = 60  # секунд: пустая комната закрывается (→ вебхук room_finished)
API_TIMEOUT = 5  # секунд


class LiveKitError(Exception):
    """LiveKit недоступен, отклонил запрос или не настроен."""


class WebhookVerificationError(LiveKitError):
    """Подпись вебхука не прошла проверку."""


def _credentials() -> tuple[str, str]:
    key, secret = settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET
    if not key or not secret:
        raise LiveKitError("LIVEKIT_API_KEY / LIVEKIT_API_SECRET не заданы")
    return key, secret


def _display_name(user) -> str:
    full_name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    return full_name or user.username or str(user.pk)


async def _room_call(method: str, request) -> None:
    key, secret = _credentials()
    if not settings.LIVEKIT_API_URL:
        raise LiveKitError("LIVEKIT_API_URL не задан")
    # ClientSession создаётся внутри цикла событий, поэтому LiveKitAPI — только здесь
    async with api.LiveKitAPI(
        settings.LIVEKIT_API_URL, key, secret, timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)
    ) as lkapi:
        await getattr(lkapi.room, method)(request)


def _run(method: str, request) -> None:
    try:
        asyncio.run(_room_call(method, request))
    except LiveKitError:
        raise
    except Exception as exc:
        raise LiveKitError(f"LiveKit {method} не выполнен: {exc}") from exc


def create_room(name: str) -> None:
    """Комната на двоих; закрывается через ROOM_EMPTY_TIMEOUT, если в неё никто не зашёл/все вышли."""
    _run(
        "create_room",
        api.CreateRoomRequest(
            name=name, max_participants=ROOM_MAX_PARTICIPANTS, empty_timeout=ROOM_EMPTY_TIMEOUT
        ),
    )


def delete_room(name: str) -> None:
    """Закрывает комнату и отключает участников."""
    _run("delete_room", api.DeleteRoomRequest(room=name))


async def _list_room_names(names: list[str]) -> set[str]:
    key, secret = _credentials()
    if not settings.LIVEKIT_API_URL:
        raise LiveKitError("LIVEKIT_API_URL не задан")
    async with api.LiveKitAPI(
        settings.LIVEKIT_API_URL, key, secret, timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)
    ) as lkapi:
        response = await lkapi.room.list_rooms(api.ListRoomsRequest(names=names))
    return {room.name for room in response.rooms}


def existing_rooms(names: list[str]) -> set[str]:
    """Какие из комнат `names` сейчас существуют в LiveKit."""
    if not names:
        return set()
    try:
        return asyncio.run(_list_room_names(list(names)))
    except LiveKitError:
        raise
    except Exception as exc:
        raise LiveKitError(f"LiveKit list_rooms не выполнен: {exc}") from exc


def access_token(user, room: str, *, video: bool) -> str:
    """Токен участника комнаты: identity = id пользователя, публикация микрофона (+ камеры для видео)."""
    key, secret = _credentials()
    sources = ["microphone", "camera"] if video else ["microphone"]
    grants = api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
        can_publish_sources=sources,
    )
    return (
        api.AccessToken(key, secret)
        .with_identity(str(user.pk))
        .with_name(_display_name(user))
        .with_grants(grants)
        .with_ttl(TOKEN_TTL)
        .to_jwt()
    )


def verify_webhook(body: str, auth_header: str) -> dict:
    """
    Проверяет подпись вебхука (JWT в Authorization с sha256 тела) и возвращает событие как dict
    с исходными (snake_case) именами полей: {"event", "room": {"name"}, "participant": {"identity"}, ...}.
    """
    token = (auth_header or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise WebhookVerificationError("Нет заголовка Authorization")
    try:
        key, secret = _credentials()
        event = api.WebhookReceiver(api.TokenVerifier(key, secret)).receive(body, token)
    except Exception as exc:
        raise WebhookVerificationError(str(exc)) from exc
    return MessageToDict(event, preserving_proto_field_name=True)
