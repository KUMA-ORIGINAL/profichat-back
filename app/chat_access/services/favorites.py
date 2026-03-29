import logging

from account.services.stream import update_channel_extra_data
from chat_access.models import FavoriteChat

logger = logging.getLogger(__name__)


def get_favorite_by(chat):
    user_ids = FavoriteChat.objects.filter(chat=chat).values_list("user_id", flat=True)
    return [str(user_id) for user_id in user_ids]


def sync_favorite_by_to_stream(chat):
    favorite_by = get_favorite_by(chat)
    try:
        update_channel_extra_data(chat.channel_id, {"favoriteBy": favorite_by})
    except Exception:
        # Источник истины — БД. Ошибка синка не должна ломать API.
        logger.exception("Failed to sync favoriteBy for channel %s", chat.channel_id)
    return favorite_by
