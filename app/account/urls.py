from django.conf import settings
from django.urls import path, include
from push_notifications.api.rest_framework import GCMDeviceAuthorizedViewSet
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView

from . import views

router = DefaultRouter()
router.register('profession-categories', views.ProfessionCategoryViewSet, basename='profession-categories')
router.register('specialists', views.SpecialistViewSet, basename='specialist')
router.register('apply', views.ApplicationCreateViewSet, basename='application-create'),
router.register(r'work-schedules', views.WorkScheduleViewSet, basename='work-schedule')
router.register(r'device/gcm', GCMDeviceAuthorizedViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('users/me/', views.UserMeViewSet.as_view(), name='user-me'),
    path('users/show-in-search/', views.UpdateShowInSearchView.as_view(), name='update-show-in-search'),
    path('users/me/update-invite-greeting/', views.UpdateInviteGreetingView.as_view(), name='update-invite-greeting'),
    path('users/me/can-call/', views.UpdateCanCallView.as_view(), name='update-can-call'),

    # path("auth/register/", views.R    egisterView.as_view(), name="register"),
    path("auth/sms/send/", views.SendSMSCodeView.as_view(), name="send_sms_code"),
    path('auth/sms/verify/', views.VerifyOTPView.as_view(), name='verify_sms_code'),
    path('auth/token/refresh/', views.CustomTokenRefreshView.as_view(), name='token_refresh'),
    path("auth/stream-token/", views.GetStreamTokenView.as_view(), name="stream_token"),
    # path('auth/password-reset/request/', views.PasswordResetRequestView.as_view(), name='password_reset_request'),
    # path('auth/password-reset/verify/', views.PasswordResetVerifyView.as_view(), name='password_reset_verify'),
    # path('auth/password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    
    path('register-fcm/', views.RegisterFCMTokenView.as_view(), name='register-fcm'),
    path('invite-client/', views.InviteClientView.as_view(), name='invite-client'),
]

if settings.DEBUG:
    urlpatterns += [
        path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    ]