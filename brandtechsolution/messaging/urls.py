from django.urls import path
from . import views

urlpatterns = [
    path("contacts/submit/", views.contact_submit, name="contact_submit"),
]
