from django.contrib import admin
from django.urls import path, include, re_path
from brand import views
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('brand.urls')),
    path('appointments/', include('appointments.urls')),
    path('api/', include('brand.api_urls')),
    path('api/ai/', include('ai_workflows.urls')),
    path('accounts/login/', views.login_view),
    path('accounts/logout/', views.logout_view),
    path('accounts/', include('django.contrib.auth.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # In production (DEBUG=False) WhiteNoise serves static but not user media,
    # so serve uploaded media files through Django.
    urlpatterns += [
        re_path(
            r'^media/(?P<path>.*)$',
            serve,
            {'document_root': settings.MEDIA_ROOT},
        ),
    ]
