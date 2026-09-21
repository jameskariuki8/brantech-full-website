"""The panel's capability list.

This is the single source of truth. It feeds StaffCapability.Meta.permissions,
the API's capability-list endpoint and the UI checkboxes, so those three cannot
drift apart.
"""

CAPABILITY_GROUPS = [
    (
        "Content",
        [
            ("manage_blog", "Manage blog posts"),
            ("publish_blog", "Publish blog posts"),
            ("manage_projects", "Manage projects"),
            ("manage_appointments", "Manage appointments"),
        ],
    ),
    (
        "Communications",
        [
            ("view_inbox", "View inbox"),
            ("handle_inquiries", "Reply to and archive inquiries"),
            ("manage_templates", "Manage email templates"),
            ("manage_campaigns", "Create and edit campaigns"),
            ("manage_recipients", "Manage campaign recipients"),
            ("send_campaigns", "Send campaigns"),
        ],
    ),
    (
        "Administration",
        [
            # Assigning and reviewing work. Note there is no "view tasks"
            # capability: the board is readable by every staff account, so
            # people can see what the team is carrying. This one gates
            # creating, assigning, approving and sending back.
            ("manage_tasks", "Assign and review tasks"),
            ("manage_staff", "Manage staff and roles"),
            # Who gets told when an agent stops working. A codename of its own
            # rather than a reuse of manage_staff: the people who should be
            # woken by a dead pipeline are not necessarily the people who
            # administer accounts, and conflating them would make giving up an
            # unrelated permission the only way to stop being paged.
            ("receive_alerts", "Receive system health alerts"),
        ],
    ),
]

ALL_CAPABILITIES = [
    pair for _label, pairs in CAPABILITY_GROUPS for pair in pairs
]

CODENAMES = [codename for codename, _label in ALL_CAPABILITIES]


def permission_tuples():
    """The list Django's Meta.permissions expects."""
    return list(ALL_CAPABILITIES)
