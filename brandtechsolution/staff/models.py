from django.conf import settings
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


class AuditEntry(models.Model):
    """Append-only record of role and account changes.

    There is no update or delete path in the API. `summary` is rendered when
    the entry is written so it still reads correctly after the user or group
    it names has been deleted.
    """

    ACTION_CHOICES = [
        ("invite_sent", "Invitation sent"),
        ("invite_revoked", "Invitation revoked"),
        ("invite_accepted", "Invitation accepted"),
        ("roles_changed", "Roles changed"),
        ("user_deactivated", "Account deactivated"),
        ("user_reactivated", "Account reactivated"),
        ("group_created", "Role created"),
        ("group_updated", "Role updated"),
        ("group_deleted", "Role deleted"),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_actions",
    )
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, db_index=True)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    target_group = models.ForeignKey(
        "auth.Group", on_delete=models.SET_NULL, null=True, blank=True
    )
    summary = models.TextField()
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "audit entries"
        default_permissions = ()

    def __str__(self):
        return self.summary
