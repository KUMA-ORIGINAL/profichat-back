from django.urls import path, include
from rest_framework.routers import SimpleRouter

from payouts import views

router = SimpleRouter()
router.register('payouts/methods', views.PayoutMethodViewSet, basename='payout-methods')
router.register('payouts/me', views.PayoutRequestViewSet, basename='my-payouts')

urlpatterns = [
    path('', include(router.urls)),
]
