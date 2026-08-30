"""«Вы врач из ErkinAI?» — предложение при регистрации и его принятие.

Человек подтвердил номер по SMS. Если в ErkinAI по этому номеру есть карточка
сотрудника, приложение показывает экран подтверждения и, получив явное «да»,
зовёт :func:`apply_card` — роль меняется на специалиста, а профиль
предзаполняется данными CRM.

Ключевое правило: **id карточки, пришедший от клиента, ничего не доказывает.**
:func:`apply_card` всегда сама заново ищет карточки по телефону *этого*
пользователя и принимает только ту, что нашлась. Иначе любой авторизованный
клиент мог бы прислать чужой ``employee_id`` и получить чужой профиль вместе с
привязкой к чужой клинике.
"""

import logging

from django.db import transaction

from account.models import Organization
from integrations.erkinai import client

logger = logging.getLogger(__name__)

GENDER_MAP = {"male": "male", "female": "female"}


def offer_for_phone(phone) -> list:
    """Карточки ErkinAI для *phone*; пустой список — предлагать нечего.

    Никогда не бросает: предложение стать специалистом — приятный бонус к
    регистрации, а не её условие. Недоступный или не настроенный ErkinAI
    означает «ничего не нашли», а не сорванную регистрацию.
    """
    if not client.is_configured():
        return []
    try:
        return client.lookup_staff_by_phone(str(phone))
    except client.ErkinAIError as exc:
        logger.warning("[ERKINAI] Поиск сотрудника по телефону не удался: %s", exc)
        return []


def find_card(phone, employee_id) -> dict | None:
    """Карточка *employee_id* среди найденных по *phone*, иначе ``None``."""
    try:
        employee_id = int(employee_id)
    except (TypeError, ValueError):
        return None
    for card in offer_for_phone(phone):
        if card.get("id") == employee_id:
            return card
    return None


@transaction.atomic
def apply_card(user, card: dict):
    """Делает *user* специалистом по карточке *card* из ErkinAI.

    Заполняются только пустые поля профиля — кроме роли и организации, которые
    и есть смысл операции. Человек мог уже что-то про себя написать до того,
    как согласился привязаться, и затирать это данными CRM неправильно.
    """
    from account.models.user import ROLE_SPECIALIST

    updated = ["role"]
    user.role = ROLE_SPECIALIST

    for field, value in _profile_updates(card).items():
        if not getattr(user, field, None) and value:
            setattr(user, field, value)
            updated.append(field)

    organization = link_organization(card.get("organization"))
    if organization is not None:
        user.organization = organization
        updated.append("organization")

    user.save(update_fields=updated)
    logger.info(
        "[ERKINAI] Пользователь %s стал специалистом по карточке %s",
        user.id,
        card.get("id"),
    )
    return user


def link_organization(payload) -> Organization | None:
    """Наша организация для организации ErkinAI из карточки.

    Заводит её, если синхронизация справочника до неё ещё не дошла: специалист
    не должен ждать крона, чтобы привязаться к своей клинике. Полноценные
    данные (адреса, статус) подтянет ближайший запуск синхронизации — он найдёт
    эту же строку по ``erkinai_id``.
    """
    if not isinstance(payload, dict):
        return None
    erkinai_id = payload.get("id")
    name = (payload.get("name") or "").strip()
    if not erkinai_id or not name:
        return None

    organization = Organization.objects.filter(erkinai_id=erkinai_id).first()
    if organization is not None:
        return organization

    existing_name = Organization.objects.filter(name=name).first()
    if existing_name is not None:
        # Одноимённая организация уже заведена руками — привязываем к ней
        # вместо того, чтобы плодить дубль с суффиксом.
        if existing_name.erkinai_id is None:
            existing_name.erkinai_id = erkinai_id
            existing_name.save(update_fields=["erkinai_id"])
        return existing_name

    return Organization.objects.create(name=name, erkinai_id=erkinai_id)


def _profile_updates(card: dict) -> dict:
    # ErkinAI хранит одно поле «ФИО» одной строкой, а у нас три отдельных.
    # Читаем его в порядке Фамилия Имя Отчество — так поле и названо в CRM.
    # Если в реальных данных окажется «Имя Фамилия», менять надо здесь и
    # только здесь; человек в любом случае правит эти поля на экране
    # подтверждения перед сохранением.
    full_name = (card.get("fullName") or "").strip().split()
    return {
        "last_name": full_name[0] if full_name else "",
        "first_name": full_name[1] if len(full_name) > 1 else "",
        "middle_name": " ".join(full_name[2:]) if len(full_name) > 2 else "",
        "description": card.get("bio") or "",
        "education": card.get("education") or "",
        "work_experience": _experience(card.get("experienceYears")),
        "gender": GENDER_MAP.get(card.get("gender") or ""),
    }


def _experience(years) -> str:
    """``work_experience`` у нас строка — храним годы как есть, текстом."""
    if years is None:
        return ""
    return str(years)
