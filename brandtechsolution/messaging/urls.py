from django.urls import path
from . import views

urlpatterns = [
    path("contacts/submit/", views.contact_submit, name="contact_submit"),
    path("unsubscribe/<str:token>/", views.unsubscribe, name="unsubscribe"),
    path("messaging/inbound-webhook/", views.mailgun_inbound_webhook, name="mailgun_inbound_webhook"),
    # Mailgun won't follow APPEND_SLASH's 301 on a POST, so a route pasted
    # without the slash would silently drop every inbound email.
    path("messaging/inbound-webhook", views.mailgun_inbound_webhook),
    path("messaging/events-webhook/", views.mailgun_events_webhook, name="mailgun_events_webhook"),
    path("messaging/events-webhook", views.mailgun_events_webhook),
]

