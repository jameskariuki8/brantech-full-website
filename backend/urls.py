from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'posts', views.BlogPostViewSet)
router.register(r'projects', views.ProjectViewSet)
router.register(r'events', views.EventViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('blog-posts/', views.blog_posts_api, name='blog-posts'),
    path('admin-panel/', views.admin_panel, name='admin-panel'),
]