from django.urls import path
from . import views

urlpatterns = [
    # Bin
    path('b/<slug:key>/', views.bin_view, name='bin_view'),
    path('b/<slug:key>/upload/', views.bin_upload, name='bin_upload'),
    path('b/<slug:key>/key-file/', views.download_key_file, name='download_key_file'),
    path('b/<slug:key>/file/<int:file_id>/download/', views.bin_file_download, name='bin_file_download'),
    path('b/<slug:key>/file/<int:file_id>/delete/', views.bin_file_delete, name='bin_file_delete'),
    path('upload/', views.bin_upload, name='bin_upload_new'),  # new bin, no key
    path('check-key/', views.bin_check_key, name='bin_check_key'),

    # Clipboard
    path('c/<slug:key>/', views.clipboard_view, name='clipboard_view'),
]