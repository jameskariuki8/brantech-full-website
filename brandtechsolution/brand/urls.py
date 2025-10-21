from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('about/', views.about, name='about'),
    path('services/', views.services, name='services'),
    path('blog/', views.blog, name='blog'),
    path('faq/', views.faq, name='faq'),
    path('contacts/', views.contacts, name='contacts'),
]
