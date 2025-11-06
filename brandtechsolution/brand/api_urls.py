from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api

router = DefaultRouter()
router.register(r'posts', api.BlogPostViewSet)
router.register(r'projects', api.ProjectViewSet)
router.register(r'events', api.EventViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('blog-posts/', api.blog_posts_api, name='blog-posts'),
]


