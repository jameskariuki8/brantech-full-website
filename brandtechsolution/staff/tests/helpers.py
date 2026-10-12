from staff.models import StaffProfile


def onboarded(user):
    """Mark a test account as having finished staff onboarding.

    The onboarding gate sends every staff account without a finished
    StaffProfile to /staff/onboarding/ before it can open a panel page, so a
    test that fetches /admin-panel/, /appointments/ or /editorial/ as a
    bare staff user needs this to reach the page it is actually testing.
    """
    StaffProfile.objects.update_or_create(user=user, defaults={"is_onboarded": True})
    return user
