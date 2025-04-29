from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('profession-categories', views.ProfessionCategoryViewSet, basename='profession-categories')
router.register('specialists', views.SpecialistViewSet, basename='specialist')
router.register('apply', views.ApplicationCreateViewSet, basename='application-create'),
router.register(r'work-schedules', views.WorkScheduleViewSet, basename='work-schedule')

urlpatterns = [
    path('', include(router.urls)),
    path('users/me/', views.UserMeViewSet.as_view(), name='user-me'),
    path('users/show-in-search/', views.UpdateShowInSearchView.as_view(), name='update-show-in-search'),
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path('auth/token/refresh/', views.CustomTokenRefreshView.as_view(), name='token_refresh'),
    path("auth/stream-token/", views.GetStreamTokenView.as_view(), name="stream_token"),
    path('auth/verify/', views.VerifyOTPView.as_view(), name='verify'),
]
