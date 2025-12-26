from django.urls import path
from . import views, api_views

urlpatterns = [
    path('', views.index, name='index'),
    path('about/', views.about, name='about'),

    # API Endpoints
    path('api/posts/', api_views.post_list, name='api_post_list'),
    path('api/posts/<int:pk>/', api_views.post_detail, name='api_post_detail'),
    path('api/projects/', api_views.project_list, name='api_project_list'),
    path('api/projects/<int:pk>/', api_views.project_detail, name='api_project_detail'),

    path('blog/', views.blog, name='blog'),

    path('projects/', views.projects, name='projects'),
    path('faq/', views.faq, name='faq'),
    path('contacts/', views.contacts, name='contacts'),
    path('admin-panel/', views.admin_panel_page, name='admin-panel'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]
