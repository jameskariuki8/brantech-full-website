from django.contrib.auth.models import Permission


def grant_all_capabilities(user):
    """Give a test's staff user every capability.

    Most messaging tests predate roles and only care that the caller is
    authorised at all. Rather than thread a capability list through each of
    them, they grant everything; the tests that specifically exercise
    capability boundaries live in test_capability_enforcement.py.
    """
    user.user_permissions.add(
        *Permission.objects.filter(content_type__app_label="staff")
    )
    user.refresh_from_db()
    return user
