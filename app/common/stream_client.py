import stream_chat
from django.conf import settings


chat_client = stream_chat.StreamChat(
    api_key=settings.STREAM_API_KEY,
    api_secret=settings.STREAM_API_SECRET
)
