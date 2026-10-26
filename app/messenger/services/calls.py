"""
Звонки 1:1 в чате через LiveKit.

Состояния: RINGING → ACCEPTED → ENDED; RINGING → DECLINED | CANCELLED | MISSED;
BUSY — сразу при старте, если у кого-то из двоих уже идёт звонок.
Каждый переход берёт блокировку строки Call (select_for_update), поэтому, например,
таймаут, пришедший одновременно с ответом, не превратит принятый звонок в пропущенный.
"""
import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from chat_access.models import BlockedChat
from common.errors import AppError, ErrorCode
from common.notifications import notify_user
from messenger import tasks
from messenger.clients import livekit
from messenger.models import Call
from messenger.serializers import CallSerializer
from messenger.services import access, events, messages as message_service
from messenger.services.push import sender_display_name

logger = logging.getLogger(__name__)

# Пространство advisory-локов «звонки пользователя» (второй ключ — id пользователя)
CALL_LOCK_NAMESPACE = 7301
# RINGING старше таймаута + запас считается зависшим (например, задача таймаута потерялась)
STALE_RINGING_GRACE = timedelta(seconds=15)
RECONCILE_ROOMS_BATCH = 100
WEBHOOK_END_EVENTS = frozenset({"participant_left", "room_finished"})
MISSED_CALL_TITLE = "Пропущенный звонок"


# --- ошибки ---

def _not_found():
    return AppError("Звонок не найден", code=ErrorCode.CALL_NOT_FOUND, status_code=404)


def _invalid_state():
    return AppError(
        "Действие недоступно в текущем состоянии звонка",
        code=ErrorCode.CALL_INVALID_STATE,
        status_code=409,
    )


def _not_allowed(message):
    return AppError(message, code=ErrorCode.CALL_NOT_ALLOWED, status_code=403)


def _unavailable():
    return AppError(
        "Сервис звонков временно недоступен",
        code=ErrorCode.REALTIME_UNAVAILABLE,
        status_code=503,
    )


# --- общее ---

def serialize_call(call) -> dict:
    return CallSerializer(call).data


def _participants(call) -> list[int]:
    return [call.caller_id, call.callee_id]


def _companion_id(chat, user_id) -> int:
    return chat.specialist_id if chat.client_id == user_id else chat.client_id


def _ring_timeout() -> timedelta:
    return timedelta(seconds=settings.MESSENGER_CALL_RING_TIMEOUT_SECONDS)


def get_call_for_user(call_id, user) -> Call:
    """Звонок, в котором пользователь участвует; иначе 404 CALL_NOT_FOUND."""
    call = (
        Call.objects.select_related("chat")
        .filter(pk=call_id)
        .filter(Q(caller_id=user.pk) | Q(callee_id=user.pk))
        .first()
    )
    if call is None:
        raise _not_found()
    return call


def _lock_users(*user_ids) -> None:
    """
    Транзакционные advisory-локи на пользователей в фиксированном порядке (без дедлоков):
    два одновременных старта с общим участником выполняются по очереди, и второй увидит первый звонок.
    """
    with connection.cursor() as cursor:
        for user_id in sorted(set(user_ids)):
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [CALL_LOCK_NAMESPACE, user_id])


def _ringing_stale_before(now):
    return now - _ring_timeout() - STALE_RINGING_GRACE


def _accepted_stale_before(now):
    return now - timedelta(seconds=settings.MESSENGER_CALL_MAX_DURATION_SECONDS)


def _is_stale_ringing(call, now) -> bool:
    return call.status == Call.Status.RINGING and call.created_at < _ringing_stale_before(now)


def _live_calls(now):
    """
    Идущие звонки: RINGING не дольше таймаута (+ запас) и ACCEPTED не дольше максимальной длительности.
    Более старые считаются зависшими (потерянный таймаут/вебхук) — их завершает `reconcile_calls`.
    """
    return Call.objects.filter(
        Q(status=Call.Status.RINGING, created_at__gte=_ringing_stale_before(now))
        | Q(status=Call.Status.ACCEPTED, answered_at__gte=_accepted_stale_before(now))
    )


def _users_calls(qs, user_ids):
    return qs.filter(Q(caller_id__in=user_ids) | Q(callee_id__in=user_ids))


def _is_busy(user_ids, now) -> bool:
    """Есть ли у кого-то из пользователей идущий звонок; зависшие RINGING отправляются на таймаут."""
    stale_ids = list(
        _users_calls(Call.objects.filter(status=Call.Status.RINGING), user_ids)
        .filter(created_at__lt=_ringing_stale_before(now))
        .values_list("pk", flat=True)
    )
    for stale_id in stale_ids:
        transaction.on_commit(lambda call_id=str(stale_id): tasks.expire_call.delay(call_id), robust=True)
    return _users_calls(_live_calls(now), user_ids).exists()


def get_active_call(user) -> Call | None:
    """Текущий идущий звонок пользователя (для восстановления клиента после перезапуска) или None."""
    return (
        _users_calls(_live_calls(timezone.now()), [user.pk])
        .select_related("chat")
        .order_by("-created_at")
        .first()
    )


def _locked(call) -> Call:
    return (
        Call.objects.select_for_update(of=("self",))
        .select_related("chat", "caller", "callee")
        .get(pk=call.pk)
    )


def _finish(call, status, reason) -> Call:
    """Завершающий переход (вызывать под блокировкой строки): сообщение, событие, закрытие комнаты."""
    now = timezone.now()
    call.status = status
    call.ended_at = now
    call.end_reason = reason
    if status == Call.Status.ENDED and call.answered_at:
        call.duration_seconds = max(0, int((now - call.answered_at).total_seconds()))
    call.save(update_fields=["status", "ended_at", "end_reason", "duration_seconds"])

    message_service.publish_call_message_updated(call)
    events.publish(_participants(call), f"call.{status}", {"call": serialize_call(call)})
    room_name = call.room_name
    transaction.on_commit(lambda: tasks.delete_call_room.delay(room_name), robust=True)
    return call


# --- старт ---

def _incoming_payload(call, caller) -> dict:
    return {
        "call": serialize_call(call),
        "caller": {"id": caller.pk, "name": sender_display_name(caller)},
    }


def start_call(chat, caller, kind) -> tuple[Call, str | None]:
    """
    Начать звонок собеседнику по чату.

    Нужен активный тариф (обеим сторонам); если собеседник внёс чат в ЧС — CALL_NOT_ALLOWED.
    Если у звонящего или собеседника уже идёт звонок — создаётся Call со статусом BUSY
    (токена нет, клиент показывает «Абонент занят»).
    """
    access.ensure_can_call(chat, caller)
    callee_id = _companion_id(chat, caller.pk)
    if BlockedChat.objects.filter(user_id=callee_id, chat=chat).exists():
        raise _not_allowed("Собеседник ограничил звонки в этом чате")

    call_id = uuid.uuid4()
    room_name = f"call_{call_id}"
    with transaction.atomic():
        _lock_users(caller.pk, callee_id)
        now = timezone.now()
        call_fields = {
            "id": call_id,
            "chat": chat,
            "caller": caller,
            "callee_id": callee_id,
            "kind": kind,
            "room_name": room_name,
            "created_at": now,
        }
        if _is_busy([caller.pk, callee_id], now):
            call = Call.objects.create(
                **call_fields, status=Call.Status.BUSY, ended_at=now, end_reason="busy"
            )
            message_service.create_call_message(chat, call)
            return call, None

        try:
            # токен до создания записи: ошибка конфигурации откатит звонок целиком
            token = livekit.access_token(caller, room_name, video=kind == Call.Kind.VIDEO)
            livekit.create_room(room_name)
        except livekit.LiveKitError:
            logger.exception("[Call] LiveKit unavailable for %s", room_name)
            raise _unavailable()

        call = Call.objects.create(**call_fields, status=Call.Status.RINGING)
        message_service.create_call_message(chat, call)
        events.publish([callee_id], "call.incoming", _incoming_payload(call, caller))
        transaction.on_commit(lambda: tasks.send_call_push.delay(str(call_id)), robust=True)
        transaction.on_commit(
            lambda: tasks.expire_call.apply_async(
                (str(call_id),), countdown=settings.MESSENGER_CALL_RING_TIMEOUT_SECONDS
            ),
            robust=True,
        )

    return call, token


def rejoin_token(call, user) -> str | None:
    """Токен комнаты для возврата в звонок: принятый — обоим, до ответа — только звонящему."""
    if call.status == Call.Status.ACCEPTED or (
        call.status == Call.Status.RINGING and user.pk == call.caller_id
    ):
        try:
            return livekit.access_token(user, call.room_name, video=call.kind == Call.Kind.VIDEO)
        except livekit.LiveKitError:
            logger.exception("[Call] LiveKit token failed for %s", call.room_name)
            raise _unavailable()
    return None


# --- переходы ---

def accept_call(call, user) -> str:
    """
    Ответ вызываемого: RINGING → ACCEPTED. Возвращает токен LiveKit.

    Зависший RINGING (таймаут потерялся) принять нельзя: он помечается MISSED и отдаётся 409.
    """
    with transaction.atomic():
        call = _locked(call)
        if user.pk != call.callee_id:
            raise _not_allowed("Принять звонок может только вызываемый")
        if call.status != Call.Status.RINGING:
            raise _invalid_state()
        if _is_stale_ringing(call, timezone.now()):
            _expire_locked(call)
            expired = True
        else:
            expired = False
            access.ensure_can_call(call.chat, user)
            try:
                token = livekit.access_token(user, call.room_name, video=call.kind == Call.Kind.VIDEO)
            except livekit.LiveKitError:
                logger.exception("[Call] LiveKit token failed for %s", call.room_name)
                raise _unavailable()

            call.status = Call.Status.ACCEPTED
            call.answered_at = timezone.now()
            call.save(update_fields=["status", "answered_at"])
            message_service.publish_call_message_updated(call)
            events.publish(_participants(call), "call.accepted", {"call": serialize_call(call)})
    if expired:
        # пропуск уже закоммичен; ошибка — вне транзакции, чтобы его не откатить
        raise _invalid_state()
    return token


def decline_call(call, user) -> Call:
    """Отказ вызываемого: RINGING → DECLINED."""
    with transaction.atomic():
        call = _locked(call)
        if user.pk != call.callee_id:
            raise _not_allowed("Отклонить звонок может только вызываемый")
        if call.status != Call.Status.RINGING:
            raise _invalid_state()
        return _finish(call, Call.Status.DECLINED, "declined")


def cancel_call(call, user) -> Call:
    """Отмена звонящим до ответа: RINGING → CANCELLED."""
    with transaction.atomic():
        call = _locked(call)
        if user.pk != call.caller_id:
            raise _not_allowed("Отменить звонок может только звонящий")
        if call.status != Call.Status.RINGING:
            raise _invalid_state()
        return _finish(call, Call.Status.CANCELLED, "cancelled")


def end_call(call, user=None, reason="hangup") -> Call:
    """
    Завершение звонка участником (или системой, user=None — вебхук LiveKit).

    ACCEPTED → ENDED с длительностью от ответа. До ответа: от звонящего — отмена,
    от вызываемого — отказ. Тариф не проверяется: истёкший во время звонка тариф его не обрывает.
    """
    with transaction.atomic():
        call = _locked(call)
        if user is not None and user.pk not in _participants(call):
            raise _not_found()
        if call.status == Call.Status.ACCEPTED:
            return _finish(call, Call.Status.ENDED, reason)
        if call.status == Call.Status.RINGING and user is not None:
            if user.pk == call.caller_id:
                return _finish(call, Call.Status.CANCELLED, "cancelled")
            return _finish(call, Call.Status.DECLINED, "declined")
        raise _invalid_state()


def expire_call(call_id) -> bool:
    """Таймаут дозвона: если звонок ещё RINGING — MISSED и пуш «Пропущенный звонок» вызываемому."""
    with transaction.atomic():
        call = (
            Call.objects.select_for_update(of=("self",))
            .select_related("chat", "caller", "callee")
            .filter(pk=call_id)
            .first()
        )
        if call is None or call.status != Call.Status.RINGING:
            return False
        _expire_locked(call)
    return True


def _expire_locked(call) -> None:
    """RINGING → MISSED (под блокировкой строки) и пуш «Пропущенный звонок» после коммита."""
    _finish(call, Call.Status.MISSED, "timeout")
    transaction.on_commit(lambda: _notify_missed(call))


def _notify_missed(call) -> None:
    # ЧС = «не беспокоить»: если вызываемый успел заблокировать чат, пуш не нужен
    if BlockedChat.objects.filter(user_id=call.callee_id, chat_id=call.chat_id).exists():
        return
    caller_name = sender_display_name(call.caller)
    kind_label = "Видеозвонок" if call.kind == Call.Kind.VIDEO else "Звонок"
    try:
        notify_user(
            user=call.callee,
            title=MISSED_CALL_TITLE,
            message=f"{kind_label} от {caller_name}",
            notification_type="missed_call",
            payload={
                "callId": str(call.pk),
                "channelId": call.chat.channel_id,
                "kind": call.kind,
                "callerId": call.caller_id,
                "callerName": caller_name,
            },
            log_prefix="[Push][MissedCall]",
        )
    except Exception:
        logger.exception("[Call] missed call notification failed for call=%s", call.pk)


# --- вебхук LiveKit ---

def handle_livekit_event(event: dict) -> None:
    """
    `participant_left` / `room_finished` для принятого звонка → ENDED (reason=disconnected),
    даже если клиент не прислал `end/`. Прочие события и чужие комнаты игнорируются.
    """
    if event.get("event") not in WEBHOOK_END_EVENTS:
        return
    room_name = (event.get("room") or {}).get("name") or ""
    if not room_name.startswith("call_"):
        return
    try:
        call_id = uuid.UUID(room_name[len("call_"):])
    except ValueError:
        return
    call = Call.objects.filter(pk=call_id, room_name=room_name).first()
    if call is None or call.status != Call.Status.ACCEPTED:
        return
    try:
        end_call(call, None, reason="disconnected")
    except AppError:
        # параллельно завершён через API — ничего делать не нужно
        pass


# --- сверка зависших звонков (Celery beat) ---

def _end_by_system(call_id, reason) -> bool:
    call = Call.objects.filter(pk=call_id).first()
    if call is None:
        return False
    try:
        end_call(call, None, reason=reason)
    except AppError:
        return False  # уже завершён параллельно
    return True


def reconcile_calls() -> dict:
    """
    Завершает зависшие звонки, которые больше никто не завершит:
    - RINGING старше таймаута (+ запас) → MISSED (потерялась задача таймаута);
    - ACCEPTED дольше MESSENGER_CALL_MAX_DURATION_SECONDS → ENDED (reason=max_duration);
    - ACCEPTED, чьей комнаты уже нет в LiveKit → ENDED (reason=disconnected): рестарт LiveKit,
      потерянный/отклонённый вебхук. Если LiveKit недоступен, эта проверка пропускается.
    """
    now = timezone.now()
    stats = {"missed": 0, "max_duration": 0, "disconnected": 0}

    stale_ringing = Call.objects.filter(
        status=Call.Status.RINGING, created_at__lt=_ringing_stale_before(now)
    ).values_list("pk", flat=True)
    for call_id in list(stale_ringing):
        stats["missed"] += int(expire_call(call_id))

    over_cap = Call.objects.filter(
        status=Call.Status.ACCEPTED, answered_at__lt=_accepted_stale_before(now)
    ).values_list("pk", flat=True)
    for call_id in list(over_cap):
        stats["max_duration"] += int(_end_by_system(call_id, "max_duration"))

    accepted = list(Call.objects.filter(status=Call.Status.ACCEPTED).values_list("pk", "room_name"))
    for start in range(0, len(accepted), RECONCILE_ROOMS_BATCH):
        batch = accepted[start:start + RECONCILE_ROOMS_BATCH]
        try:
            existing = livekit.existing_rooms([room_name for _, room_name in batch])
        except livekit.LiveKitError:
            logger.warning("[Call] reconcile: LiveKit list_rooms failed, room check skipped", exc_info=True)
            break
        for call_id, room_name in batch:
            if room_name not in existing:
                stats["disconnected"] += int(_end_by_system(call_id, "disconnected"))
    return stats
