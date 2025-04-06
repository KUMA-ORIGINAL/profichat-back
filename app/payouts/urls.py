from django.urls import path, include
from rest_framework.routers import DefaultRouter

from payouts import views

router = DefaultRouter()
router.register('payouts/methods', views.PayoutMethodViewSet, basename='payout-methods')
router.register('payouts/me', views.PayoutRequestViewSet, basename='my-payouts')

urlpatterns = [
    path('', include(router.urls)),
]
