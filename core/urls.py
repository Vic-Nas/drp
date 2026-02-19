from django.urls import path, re_path
from django.contrib.auth import views as auth_views
from core import views
from core.views.error_reporting import report_error

# Matches any key that doesn't contain / or whitespace
KEY = r'(?P<key>[^/\s]+)'

urlpatterns = [
    # ── Utilities ─────────────────────────────────────────────────────────────
    path('api/report-error/', report_error, name='report_error'),
    path('save/', views.save_drop, name='save_drop'),
    path('check-key/', views.check_key, name='check_key'),
    path('help/', views.help_view, name='help'),

    # ── Auth ──────────────────────────────────────────────────────────────────
    path('auth/register/', views.register_view, name='register'),
    path('auth/login/', views.login_view, name='login'),
    path('auth/logout/', views.logout_view, name='logout'),
    path('auth/account/', views.account_view, name='account'),
    path('auth/account/export/', views.export_drops, name='export_drops'),

    # ── Password reset ────────────────────────────────────────────────────────
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

    # ── File drops ────────────────────────────────────────────────────────────
    re_path(rf'^f/{KEY}/download/$', views.download_drop, name='download_drop'),
    re_path(rf'^f/{KEY}/rename/$',   views.rename_drop, {'ns': 'f'}, name='rename_file'),
    re_path(rf'^f/{KEY}/delete/$',   views.delete_drop, {'ns': 'f'}, name='delete_file'),
    re_path(rf'^f/{KEY}/renew/$',    views.renew_drop,  {'ns': 'f'}, name='renew_file'),
    re_path(rf'^f/{KEY}/$',          views.file_view,               name='file_view'),

    # ── Clipboard drops ───────────────────────────────────────────────────────
    # Must be last — catches /key/ for clipboard access and actions.
    re_path(rf'^{KEY}/rename/$', views.rename_drop, {'ns': 'c'}, name='rename_clipboard'),
    re_path(rf'^{KEY}/delete/$', views.delete_drop, {'ns': 'c'}, name='delete_clipboard'),
    re_path(rf'^{KEY}/renew/$',  views.renew_drop,  {'ns': 'c'}, name='renew_clipboard'),
    re_path(rf'^{KEY}/$',        views.clipboard_view,            name='clipboard_view'),
]