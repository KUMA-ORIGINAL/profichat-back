"""Тихие часы специалиста.

Пуши чата специалисту шлёт Stream, и придержать их до утра он не умеет —
только выключить до заданного момента (push preferences, `disabled_until`).
Поэтому в нерабочее время по графику пуши чата выключаются до начала
следующей смены, а когда смена начинается, бэк сам шлёт одну сводку:
сколько оформлено тарифов и сколько непрочитанных сообщений.

Правила графика повторяют приложение (`work_schedule_provider.dart`): смена
через полночь заканчивается на следующий день, круглосуточный день — от
полуночи до полуночи, выходной и нерабочая дата — не работает, день без
записи в графике — тоже. Обед считаем рабочим временем: глушить пуши на час
и слать сводку после обеда незачем.

`disabled_until` — сам по себе страховка: если планировщик встанет, Stream
включит пуши обратно к началу смены, просто без сводки.
"""

import logging
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone

from django.db.models import Q
from django.utils import timezone

from common.notifications import notify_user
from common.stream_client import chat_client

logger = logging.getLogger(__name__)

# Насколько вперёд искать следующую смену. Если её нет и за это время
# (отпуск, все дни выходные), тишину не включаем: глушить пуши на недели
# без сводки хуже, чем разбудить.
LOOKAHEAD_DAYS = 14

SUMMARY_TITLE = "Пока вас не было"


def _local_dt(day, clock):
    return timezone.make_aware(datetime.combine(day, clock))


def _shift(day, schedule, off_dates):
    """Смена, начавшаяся в день `day`, как (начало, конец) или None."""
    if day in off_dates or schedule is None or schedule.is_day_off:
        return None
    if schedule.is_round_the_clock:
        return _local_dt(day, time.min), _local_dt(day + timedelta(days=1), time.min)

    start_clock = schedule.from_time or time.min
    end_clock = schedule.to_time or time.min
    if start_clock == end_clock:
        return None
    end_day = day if end_clock > start_clock else day + timedelta(days=1)
    return _local_dt(day, start_clock), _local_dt(end_day, end_clock)


def _shifts(user, moment):
    today = timezone.localtime(moment).date()
    first, last = today - timedelta(days=1), today + timedelta(days=LOOKAHEAD_DAYS)
    schedules = {s.day_of_week: s for s in user.work_schedules.all()}
    off_dates = set(
        user.non_working_dates.filter(date__gte=first, date__lte=last).values_list("date", flat=True)
    )
    day = first
    while day <= last:
        shift = _shift(day, schedules.get(day.isoweekday()), off_dates)
        if shift:
            yield shift
        day += timedelta(days=1)


def quiet_until(user, moment):
    """До какого момента у специалиста тишина; None — тишины нет.

    None и когда смена идёт сейчас, и когда смен впереди не найдено.
    """
    next_start = None
    for start, end in _shifts(user, moment):
        if start <= moment < end:
            return None
        if start > moment and (next_start is None or start < next_start):
            next_start = start
    return next_start


def available_from(user, moment):
    """С какого момента специалист отвечает: `moment`, если смена идёт или
    графика нет, иначе начало следующей смены."""
    return quiet_until(user, moment) or moment


def _stream_time(moment):
    return moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pause_chat_pushes(user, until):
    chat_client.post(
        "push_preferences",
        data={"preferences": [{
            "user_id": str(user.id),
            "chat_level": "all",
            "disabled_until": _stream_time(until),
        }]},
    )


def resume_chat_pushes(user):
    chat_client.post(
        "push_preferences",
        data={"preferences": [{"user_id": str(user.id), "remove_disable": True}]},
    )


def _plural(number, one, many):
    """Родительный падеж после «от N»: от 1 клиента, от 5 клиентов."""
    return one if number % 10 == 1 and number % 100 != 11 else many


def summary_text(orders, messages, clients):
    """Текст сводки или None, если сообщать нечего."""
    parts = []
    if orders:
        parts.append(f"Оформлено тарифов: {orders}.")
    if messages:
        parts.append(
            f"Непрочитанных сообщений: {messages} "
            f"от {clients} {_plural(clients, 'клиента', 'клиентов')}."
        )
    return " ".join(parts) or None


def missed_while_quiet(user, since):
    """Сколько тарифов оформлено с `since` и сколько сейчас непрочитанного."""
    from chat_access.models import AccessOrder

    orders = AccessOrder.objects.filter(
        specialist=user,
        payment_status="success",
        activated_at__gte=since,
    ).count()

    unread = chat_client.unread_counts(str(user.id))
    messages = unread.get("total_unread_count", 0) or 0
    clients = sum(1 for channel in unread.get("channels", []) if channel.get("unread_count"))
    return orders, messages, clients


def send_quiet_hours_summary(user, since):
    from account.models import Notification

    text = summary_text(*missed_while_quiet(user, since))
    if not text:
        return False
    notify_user(
        user=user,
        title=SUMMARY_TITLE,
        message=text,
        notification_type=Notification.TYPE_QUIET_HOURS_SUMMARY,
        log_prefix="[Push][QuietHours]",
    )
    return True


def _wants_quiet_hours(user):
    from account.models import ROLE_SPECIALIST

    return user.is_active and user.role == ROLE_SPECIALIST and not user.notify_outside_work_hours


def end_quiet_hours(user, send_summary):
    """Включить пуши обратно и, если просили, прислать сводку пропущенного."""
    from account.models import QuietHoursState

    state = QuietHoursState.objects.filter(user=user).first()
    if state is None:
        return
    resume_chat_pushes(user)
    if send_summary:
        try:
            send_quiet_hours_summary(user, state.quiet_since)
        except Exception:
            # Сводка — приятное дополнение: из-за её сбоя тишину не держим.
            logger.exception("[QuietHours] Summary failed for user_id=%s", user.id)
    state.delete()


def sync_quiet_hours(user, now=None):
    """Привести тишину специалиста в соответствие с графиком на момент `now`."""
    from account.models import QuietHoursState

    now = now or timezone.now()
    until = quiet_until(user, now) if _wants_quiet_hours(user) else None
    state = QuietHoursState.objects.filter(user=user).first()

    if until is None:
        if state is not None:
            # Сводку шлём только когда тишина кончилась началом смены, а не
            # тем, что специалист включил «Получать всегда» или перестал им быть.
            end_quiet_hours(user, send_summary=_wants_quiet_hours(user))
        return

    if state is not None and state.muted_until == until:
        return
    pause_chat_pushes(user, until)
    if state is None:
        QuietHoursState.objects.create(user=user, quiet_since=now, muted_until=until)
    else:
        # График поменяли посреди ночи — двигаем конец тишины, начало не трогаем.
        state.muted_until = until
        state.save(update_fields=["muted_until", "updated_at"])


def sync_all_quiet_hours(now=None):
    from account.models import ROLE_SPECIALIST, User

    now = now or timezone.now()
    users = (
        User.objects.filter(
            Q(role=ROLE_SPECIALIST, is_active=True, notify_outside_work_hours=False)
            | Q(quiet_hours__isnull=False)
        )
        .distinct()
        .prefetch_related("work_schedules")
    )
    for user in users:
        try:
            sync_quiet_hours(user, now)
        except Exception:
            # Один сбой Stream не должен останавливать остальных: повторим
            # на следующем проходе.
            logger.exception("[QuietHours] Sync failed for user_id=%s", user.id)
