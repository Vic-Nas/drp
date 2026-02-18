from django.urls import path
from . import views

urlpatterns = [
    path('checkout/<str:plan>/', views.checkout, name='billing_checkout'),
    path('portal/', views.portal, name='billing_portal'),
    path('webhook/', views.webhook, name='billing_webhook'),
]