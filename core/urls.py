from django.urls import path
from django.contrib.auth import views as auth_views
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
    path('auth/account/', views.account_view, name='account'),

    # Password reset — Django's built-in views, our templates
    path('auth/forgot-password/',
         auth_views.PasswordResetView.as_view(
             template_name='registration/password_reset_form.html',
             email_template_name='registration/password_reset_email.html',
             subject_template_name='registration/password_reset_subject.txt',
         ),
         name='forgot_password'),
    path('auth/forgot-password/done/',
         auth_views.PasswordResetDoneView.as_view(
             template_name='registration/password_reset_done.html',
         ),
         name='password_reset_done'),
    path('auth/reset/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(
             template_name='registration/password_reset_confirm.html',
         ),
         name='password_reset_confirm'),
    path('auth/reset/done/',
         auth_views.PasswordResetCompleteView.as_view(
             template_name='registration/password_reset_complete.html',
         ),
         name='password_reset_complete'),

    # Drop actions
    path('<slug:key>/', views.drop_view, name='drop_view'),
    path('<slug:key>/download/', views.download_drop, name='download_drop'),
    path('<slug:key>/rename/', views.rename_key, name='rename_key'),
    path('<slug:key>/delete/', views.delete_drop, name='delete_drop'),
    path('<slug:key>/renew/', views.renew_drop, name='renew_drop'),
]