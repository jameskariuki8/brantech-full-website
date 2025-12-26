from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('brand.urls')),
    path('appointments/', include('appointments.urls')),
    path('api/', include('brand.api_urls')),
    path('api/ai/', include('ai_workflows.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
