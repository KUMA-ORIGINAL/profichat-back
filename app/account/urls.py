from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('profession-categories', views.ProfessionCategoryViewSet, basename='profession-categories')
router.register('specialists', views.SpecialistViewSet, basename='specialist')
router.register('apply', views.ApplicationCreateViewSet, basename='application-create'),

urlpatterns = [
    path('', include(router.urls)),
    path('users/me/', views.UserMeViewSet.as_view(), name='user-me'),
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/stream-token/", views.GetStreamTokenView.as_view(), name="stream_token"),
]
