from django.urls import path, include
from rest_framework.routers import DefaultRouter

from chat_access import views

router = DefaultRouter()
router.register(r'tariffs', views.TariffViewSet)
router.register(r'access-orders', views.AccessOrderViewSet)


urlpatterns = [
    path('', include(router.urls)),
]
