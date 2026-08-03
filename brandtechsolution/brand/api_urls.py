from django.urls import path

from . import api

urlpatterns = [
    path('blog-posts/', api.blog_posts_api, name='blog-posts'),
    path('admin/stats/', api.dashboard_stats, name='admin-stats'),
]
