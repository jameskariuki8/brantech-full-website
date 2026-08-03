from types import SimpleNamespace

from .capabilities import CODENAMES


def held_capabilities(user):
    """The capability set for one user, as (list, namespace).

    `can` is a SimpleNamespace and deliberately not a dict. Django resolves
    `can.x` by dictionary lookup first and *attribute* lookup second, so with
    a dict a capability codename that collided with a dict method name (items,
    keys, values, get, update, copy, pop, clear) would resolve to a bound
    method - truthy - and render that section for every user. A namespace
    removes the class of bug outright. staff.tests.test_panel_rendering
    .CapabilityNamingTest pins the guarantee.
    """
    if not (user and user.is_authenticated and user.is_staff):
        return [], SimpleNamespace()
    held = sorted(c for c in CODENAMES if user.has_perm(f"staff.{c}"))
    return held, SimpleNamespace(**{c: True for c in held})


def capabilities(request):
    """Put `can` in front of every template that extends the panel shell.

    admin_base.html gates its nav on `can`, and it is extended by the
    appointments and editorial pages as well as admin_panel.html. Those views
    do not build the capability set themselves, so without this the gates
    would read every codename as false and their sidebars would come out
    empty. A context processor is the only place that covers all of them at
    once, including any page added later.

    Gating in templates is cosmetic - every API enforces its own capability.
    """
    held, can = held_capabilities(getattr(request, "user", None))
    return {"capabilities": held, "can": can}
