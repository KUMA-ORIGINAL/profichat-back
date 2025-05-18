from django.urls import path, include
from rest_framework.routers import DefaultRouter

from chat_access import views

router = DefaultRouter()
router.register(r'tariffs', views.TariffViewSet, basename='tariffs')
router.register(r'access-orders', views.AccessOrderViewSet, basename='access-orders')
router.register('payment/webhook', views.PaymentWebhookViewSet, basename='payment_webhook')


urlpatterns = [
    path('', include(router.urls)),
]
