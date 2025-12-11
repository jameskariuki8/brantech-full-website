from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('about/', views.about, name='about'),

    path('blog/', views.blog, name='blog'),
    path('events/', views.events, name='events'),
    path('projects/', views.projects, name='projects'),
    path('faq/', views.faq, name='faq'),
    path('contacts/', views.contacts, name='contacts'),
    path('admin-panel/', views.admin_panel_page, name='admin-panel'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]
