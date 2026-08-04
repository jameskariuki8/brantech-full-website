"""Editor review notifications go to the people who can approve the draft."""
from django.contrib.auth.models import Permission, User
from django.core import mail
from django.test import TestCase, override_settings

from approval.services.workflow import HumanApprovalWorkflow
from editorial.models import EditorialArticle


class NotifyEditorsTest(TestCase):
    def setUp(self):
        self.article = EditorialArticle.objects.create(
            title="A Draft Awaiting Review",
            executive_summary="Summary text.",
        )
        self.workflow = HumanApprovalWorkflow()

    def _make_editor(self, username, email):
        user = User.objects.create_user(username, email, "pw", is_staff=True)
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="staff", codename="publish_blog"
            )
        )
        return user

    def test_every_publish_blog_holder_is_notified(self):
        self._make_editor("ed1", "ed1@example.com")
        self._make_editor("ed2", "ed2@example.com")

        self.workflow.notify_editors(self.article)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            sorted(mail.outbox[0].to), ["ed1@example.com", "ed2@example.com"]
        )
        self.assertIn("A Draft Awaiting Review", mail.outbox[0].subject)

    def test_staff_without_the_capability_are_not_notified(self):
        self._make_editor("ed1", "ed1@example.com")
        User.objects.create_user("writer", "writer@example.com", "pw", is_staff=True)

        self.workflow.notify_editors(self.article)

        self.assertEqual(mail.outbox[0].to, ["ed1@example.com"])

    @override_settings(EDITORIAL_REVIEW_EMAIL="fallback@example.com")
    def test_the_configured_inbox_covers_a_deployment_with_no_holders_yet(self):
        self.workflow.notify_editors(self.article)

        self.assertEqual(mail.outbox[0].to, ["fallback@example.com"])

    @override_settings(EDITORIAL_REVIEW_EMAIL="fallback@example.com")
    def test_the_fallback_is_not_used_once_a_holder_exists(self):
        self._make_editor("ed1", "ed1@example.com")

        self.workflow.notify_editors(self.article)

        self.assertEqual(mail.outbox[0].to, ["ed1@example.com"])

    @override_settings(EDITORIAL_REVIEW_EMAIL="")
    def test_no_recipients_sends_nothing_but_still_advances_the_article(self):
        """The draft must still reach review_pending and be visible on the
        dashboard -- the notification is a convenience, not the workflow."""
        with self.assertLogs("approval.services.workflow", level="WARNING") as logs:
            self.workflow.notify_editors(self.article)

        self.assertEqual(mail.outbox, [])
        self.assertIn("nobody notified", "\n".join(logs.output))
        self.article.refresh_from_db()
        self.assertEqual(self.article.status, "review_pending")
