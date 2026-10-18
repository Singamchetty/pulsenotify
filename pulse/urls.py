from django.urls import path

from . import views

urlpatterns = [
    path('auth/register/', views.RegisterView.as_view()),
    path('auth/login/', views.LoginView.as_view()),
    path('alerts/', views.AlertListCreateView.as_view()),
    path('alerts/<int:id>/', views.AlertDeactivateView.as_view()),
    path('flights/price/', views.get_flight_price),
    path('admin/summary/', views.AdminSummaryView.as_view()),
]
