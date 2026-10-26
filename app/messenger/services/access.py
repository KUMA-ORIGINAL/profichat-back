from django.db.models import Q
from django.utils import timezone

from chat_access.models import Chat
from common.errors import AppError, ErrorCode


def has_active_tariff(chat, now=None) -> bool:
    """Есть ли у чата оплаченный и ещё не истёкший доступ."""
    now = now or timezone.now()
    return chat.access_orders.filter(payment_status="success", expires_at__gt=now).exists()


def ensure_member(user, channel_id) -> Chat:
    """Чат по публичному channel_id, если пользователь в нём участник; иначе 404 CHAT_NOT_FOUND."""
    chat = (
        Chat.objects.filter(channel_id=channel_id)
        .filter(Q(client_id=user.pk) | Q(specialist_id=user.pk))
        .first()
    )
    if chat is None:
        raise AppError("Чат не найден", code=ErrorCode.CHAT_NOT_FOUND, status_code=404)
    return chat


def _tariff_required():
    return AppError(
        "Для этого действия нужен активный тариф",
        code=ErrorCode.TARIFF_REQUIRED,
        status_code=403,
    )


def _is_client(chat, user) -> bool:
    return chat.client_id == user.pk


def ensure_can_send(chat, user) -> None:
    """Клиенту писать можно только при активном тарифе; специалисту — всегда."""
    if _is_client(chat, user) and not has_active_tariff(chat):
        raise _tariff_required()


def ensure_can_send_voice(chat, user) -> None:
    ensure_can_send(chat, user)
    if _is_client(chat, user) and not chat.client_can_send_voice:
        raise AppError(
            "Отправка голосовых сообщений запрещена специалистом",
            code=ErrorCode.VOICE_NOT_ALLOWED,
            status_code=403,
        )


def ensure_can_call(chat, user) -> None:
    """Звонки (начать/принять) нужны обеим сторонам только при активном тарифе."""
    if not has_active_tariff(chat):
        raise _tariff_required()
