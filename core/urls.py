from django.urls import path
from . import views

urlpatterns = [
    # Core
    path('save/', views.save_drop, name='save_drop'),
    path('check-key/', views.check_key, name='check_key'),
    path('help/', views.help_view, name='help'),

    # Auth
    path('auth/register/', views.register_view, name='register'),
    path('auth/login/', views.login_view, name='login'),
    path('auth/logout/', views.logout_view, name='logout'),
    path('auth/forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('auth/account/', views.account_view, name='account'),

    # Drop actions
    path('<slug:key>/', views.drop_view, name='drop_view'),
    path('<slug:key>/download/', views.download_drop, name='download_drop'),
    path('<slug:key>/rename/', views.rename_key, name='rename_key'),
    path('<slug:key>/delete/', views.delete_drop, name='delete_drop'),
    path('<slug:key>/renew/', views.renew_drop, name='renew_drop'),
]