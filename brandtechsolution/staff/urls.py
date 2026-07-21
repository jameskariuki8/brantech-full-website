from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("invite/<str:token>/", views.accept_invitation, name="accept-invitation"),
]
