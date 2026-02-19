from django.contrib import admin
from django.urls import path, include
from core import views

handler500 = 'core.views.error_handler.server_error'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('billing/', include('billing.urls')),
    path('help/', include('help.urls')),
    path('', include('core.urls')),
]