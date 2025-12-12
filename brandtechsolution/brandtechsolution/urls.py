from django.contrib import admin
from django.urls import path, include
from brand import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('brand.urls')),
    path('appointments/', include('appointments.urls')),
    path('api/', include('brand.api_urls')),
    path('accounts/login/', views.login_view), 
    path('accounts/logout/', views.logout_view),
    path('accounts/', include('django.contrib.auth.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
