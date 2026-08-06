from django.urls import path
from . import views

urlpatterns = [
    path("contacts/submit/", views.contact_submit, name="contact_submit"),
    path("unsubscribe/<str:token>/", views.unsubscribe, name="unsubscribe"),
    path("messaging/inbound-webhook/", views.mailgun_inbound_webhook, name="mailgun_inbound_webhook"),
]

