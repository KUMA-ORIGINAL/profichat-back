from django.urls import path, include
from rest_framework.routers import DefaultRouter

from chat_access import views

router = DefaultRouter()
router.register(r'tariffs', views.TariffViewSet, basename='tariffs')
router.register(r'access-orders', views.AccessOrderViewSet, basename='access-orders')
router.register('payment/webhook', views.PaymentWebhookViewSet, basename='payment_webhook')
router.register(r'chats', views.ChatViewSet, basename='chat')
router.register(r'stream/send-system-message', views.StreamSystemMessageViewSet, basename='stream-system-message')


urlpatterns = [
    path('', include(router.urls)),
]
