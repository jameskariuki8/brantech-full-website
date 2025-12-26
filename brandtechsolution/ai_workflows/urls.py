from django.urls import path
from . import views

app_name = 'ai_workflows'

urlpatterns = [
    path('chat/', views.chat_endpoint, name='chat'),
    path('chat/history/', views.chat_history, name='chat_history'),
    path('chat/clear/', views.clear_chat_history, name='clear_chat_history'),
]

