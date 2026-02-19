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
    path('auth/account/export/', views.export_drops, name='export_drops'),

    # Password reset
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

    # ── Namespaced drop URLs ───────────────────────────────────────────────────
    # Canonical: /c/<key>/ for clipboards, /f/<key>/ for files
    path('c/<slug:key>/', views.clipboard_view, name='clipboard_view'),
    path('f/<slug:key>/', views.file_view, name='file_view'),
    path('f/<slug:key>/download/', views.download_drop, name='download_drop'),

    # Drop actions — namespace included so server knows which drop
    path('c/<slug:key>/rename/', views.rename_key, {'ns': 'c'}, name='rename_clipboard'),
    path('f/<slug:key>/rename/', views.rename_key, {'ns': 'f'}, name='rename_file'),
    path('c/<slug:key>/delete/', views.delete_drop, {'ns': 'c'}, name='delete_clipboard'),
    path('f/<slug:key>/delete/', views.delete_drop, {'ns': 'f'}, name='delete_file'),
    path('c/<slug:key>/renew/', views.renew_drop, {'ns': 'c'}, name='renew_clipboard'),
    path('f/<slug:key>/renew/', views.renew_drop, {'ns': 'f'}, name='renew_file'),

    # ── Short URL resolver ─────────────────────────────────────────────────────
    # /key/ → resolves to /c/key/ or /f/key/ — for sharing
    # Must be last to avoid shadowing everything above
    path('<slug:key>/', views.resolve_key, name='resolve_key'),
]