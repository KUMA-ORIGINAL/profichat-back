from django.urls import path

from . import views

urlpatterns = [
    path('corporate-poll/', views.StateView.as_view()),
    path('corporate-poll/places/', views.PlaceCreateView.as_view()),
    path('corporate-poll/places/<int:pk>/', views.PlaceDeleteView.as_view()),
    path('corporate-poll/votes/', views.VoteView.as_view()),
    path('corporate-poll/wish/', views.WishView.as_view()),
]
