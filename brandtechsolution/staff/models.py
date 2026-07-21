from django.db import models

from .capabilities import permission_tuples


class StaffCapability(models.Model):
    """Owns the panel's permissions. Has no table and never holds rows.

    Django requires a permission to hang off a model. Attaching these to
    BlogPost, Campaign and friends would bury them among the auto-generated
    CRUD permissions, so they live here instead. managed = False means no
    table is created; default_permissions = () suppresses add/change/delete/
    view. post_migrate still creates the auth_permission rows, so these behave
    as ordinary Django permissions.
    """

    class Meta:
        managed = False
        default_permissions = ()
        permissions = permission_tuples()
