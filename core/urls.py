from django.urls import path
from . import views

urlpatterns = [
    path('save/', views.save_drop, name='save_drop'),
    path('check-key/', views.check_key, name='check_key'),
    path('<slug:key>/', views.drop_view, name='drop_view'),
    path('<slug:key>/download/', views.download_drop, name='download_drop'),
    path('<slug:key>/rename/', views.rename_key, name='rename_key'),
    path('<slug:key>/delete/', views.delete_drop, name='delete_drop'),
]