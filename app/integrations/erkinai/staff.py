"""«Вы врач из ErkinAI?» — предложение при регистрации и его принятие.

Человек подтвердил номер по SMS. Если в ErkinAI по этому номеру есть карточка
сотрудника, приложение показывает экран подтверждения и, получив явное «да»,
зовёт :func:`apply_card` — роль меняется на специалиста, а профиль
предзаполняется данными CRM.

Ключевое правило: **id карточки, пришедший от клиента, ничего не доказывает.**
:func:`apply_card` вызывается только после того, как :func:`find_card` заново
нашла карточки по телефону *этого* пользователя. Иначе любой авторизованный
клиент мог бы прислать чужой ``employee_id`` и получить чужой профиль.

Организацию из CRM мы **не заводим**: человек выбирает её из нашего
справочника (`GET /api/organizations/`). Названия клиник у нас и в ErkinAI
живут своей жизнью, и автосоздание по одному лишь совпадению имени плодило бы
почти-дубликаты, которые потом разбирать руками. Организация из карточки
приходит в предложении и годится, чтобы подсветить нужный пункт списка, — но
решает человек.
"""

import logging

from django.db import transaction

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
def apply_card(user, card: dict, organization=None):
    """Делает *user* специалистом по карточке *card* из ErkinAI.

    *organization* — выбранная человеком из нашего справочника; ``None``
    значит «пока не выбрал», и тогда привязка просто не трогается. Блокировать
    из-за этого получение роли незачем: организацию можно указать и позже, а
    клиники может не оказаться в списке в момент регистрации.

    Заполняются только пустые поля профиля — кроме роли. Человек мог уже
    что-то про себя написать до того, как согласился привязаться, и затирать
    это данными CRM неправильно.
    """
    from account.models.user import ROLE_SPECIALIST

    updated = ["role"]
    user.role = ROLE_SPECIALIST

    for field, value in _profile_updates(card).items():
        if not getattr(user, field, None) and value:
            setattr(user, field, value)
            updated.append(field)

    if organization is not None:
        user.organization = organization
        updated.append("organization")

    user.save(update_fields=updated)
    logger.info(
        "[ERKINAI] Пользователь %s стал специалистом по карточке %s (организация %s)",
        user.id,
        card.get("id"),
        organization.id if organization is not None else "не выбрана",
    )
    return user


def _profile_updates(card: dict) -> dict:
    # ErkinAI хранит одно поле «ФИО» одной строкой, а у нас три отдельных.
    # Читаем его в порядке Фамилия Имя Отчество — так поле и названо в CRM,
    # и так приходят реальные данные («Юлдашева Зарифа Мажитовна»). Человек в
    # любом случае правит эти поля на экране подтверждения перед сохранением.
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
