import json
from channels.generic.websocket import AsyncWebsocketConsumer


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.chat_id = self.scope['url_route']['kwargs']['channel_id']
        self.group_name = f"chat_{self.chat_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        """Принимаем сообщение от клиента и пересылаем в группу"""
        data = json.loads(text_data)
        message = data.get("message")

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "message": message,
                "sender": self.scope["user"].username,
            }
        )

    async def user_update(self, event):
        """Рассылка инфы, что обновились данные пользователя"""
        await self.send(json.dumps({
            "type": "user_update",
            "user": event["user"],
            "changes": event.get("changes"),
        }))