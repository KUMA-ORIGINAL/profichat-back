from django.apps import AppConfig


class ChatAccessConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'chat_access'

    def ready(self):
        import chat_access.signals