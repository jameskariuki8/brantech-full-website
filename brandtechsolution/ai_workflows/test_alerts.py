"""Step 5: alerting, and the themed mail it sends.

The suite never sends real mail -- settings.py already forces the locmem
backend under test -- so `mail.outbox` is the assertion surface.
"""
from django.contrib.auth.models import Permission, User
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from ai_workflows.harness.alerts import (
    ALERT_CAPABILITY,
    alert_recipients,
    record_failure,
    record_success,
)
from ai_workflows.harness.errors import AgentOutputInvalid, ModelUnavailable
from ai_workflows.models import AgentHealth
from brandtechsolution.mail import render_mail, send_mail_html


def _holder(username, email):
    user = User.objects.create_user(username, email=email, is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename=ALERT_CAPABILITY))
    return user


class RecipientTests(TestCase):
    def test_holders_of_the_capability_are_the_recipients(self):
        _holder("ops", "ops@example.com")
        self.assertEqual(alert_recipients(), ["ops@example.com"])

    def test_a_staff_member_without_the_capability_is_not_paged(self):
        User.objects.create_user("editor", email="editor@example.com", is_staff=True)
        self.assertEqual(alert_recipients(), [])

    def test_the_capability_is_separate_from_manage_staff(self):
        """Giving up account administration must not be the way to stop being paged."""
        user = User.objects.create_user("admin", email="admin@example.com", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename="manage_staff"))
        self.assertEqual(alert_recipients(), [])

    def test_a_superuser_is_included(self):
        User.objects.create_superuser("root", email="root@example.com", password="x")
        self.assertIn("root@example.com", alert_recipients())


class StateChangeTests(TestCase):
    """Alerts fire on a state change, not per failure."""

    def setUp(self):
        _holder("ops", "ops@example.com")

    def test_the_first_failure_alerts(self):
        self.assertTrue(record_failure("fact_verifier", ModelUnavailable("no key")))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("fact_verifier is failing", mail.outbox[0].subject)

    def test_the_same_failure_again_is_counted_not_sent(self):
        """A dead provider fails every stage of every run; one mail each would
        replace silence with a storm, and a storm gets filtered."""
        record_failure("fact_verifier", ModelUnavailable("no key"))
        mail.outbox.clear()

        for _ in range(5):
            self.assertFalse(record_failure("fact_verifier", ModelUnavailable("no key")))

        self.assertEqual(mail.outbox, [])
        self.assertEqual(
            AgentHealth.objects.get(agent="fact_verifier").suppressed_since_alert, 5
        )

    def test_a_different_error_class_alerts_again(self):
        """ModelUnavailable then AgentOutputInvalid is a new problem."""
        record_failure("writer", ModelUnavailable("no key"))
        mail.outbox.clear()

        self.assertTrue(record_failure("writer", AgentOutputInvalid("bad shape")))
        self.assertEqual(len(mail.outbox), 1)

    def test_the_suppressed_count_reaches_the_message(self):
        record_failure("writer", ModelUnavailable("no key"))
        for _ in range(3):
            record_failure("writer", ModelUnavailable("no key"))
        mail.outbox.clear()

        record_failure("writer", AgentOutputInvalid("bad shape"))
        body = mail.outbox[0].alternatives[0][0]
        self.assertIn("3", body)

    def test_recovery_alerts_once(self):
        record_failure("writer", ModelUnavailable("no key"))
        mail.outbox.clear()

        self.assertTrue(record_success("writer"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("working again", mail.outbox[0].subject)

    def test_a_healthy_agent_succeeding_says_nothing(self):
        record_success("writer")
        record_success("writer")
        self.assertEqual(mail.outbox, [])

    def test_recovery_clears_the_failure_state(self):
        record_failure("writer", ModelUnavailable("no key"))
        record_success("writer")

        health = AgentHealth.objects.get(agent="writer")
        self.assertEqual(health.status, AgentHealth.HEALTHY)
        self.assertIsNone(health.failing_since)
        self.assertEqual(health.error_class, "")

    def test_failing_again_after_recovery_alerts_again(self):
        record_failure("writer", ModelUnavailable("no key"))
        record_success("writer")
        mail.outbox.clear()

        self.assertTrue(record_failure("writer", ModelUnavailable("no key")))
        self.assertEqual(len(mail.outbox), 1)

    def test_failing_since_marks_the_start_not_the_latest(self):
        record_failure("writer", ModelUnavailable("no key"))
        started = AgentHealth.objects.get(agent="writer").failing_since

        record_failure("writer", ModelUnavailable("no key"))
        self.assertEqual(AgentHealth.objects.get(agent="writer").failing_since, started)

    def test_agents_fail_independently(self):
        record_failure("writer", ModelUnavailable("no key"))
        mail.outbox.clear()

        self.assertTrue(record_failure("fact_verifier", ModelUnavailable("no key")))
        self.assertEqual(len(mail.outbox), 1)


class NobodyToTellTests(TestCase):
    def test_a_failure_with_no_holders_is_logged_loudly(self):
        """Not raising -- the agent already failed -- but not silent either."""
        with self.assertLogs("ai_workflows.harness.alerts", level="ERROR") as logs:
            sent = record_failure("writer", ModelUnavailable("no key"))

        self.assertFalse(sent)
        self.assertEqual(mail.outbox, [])
        self.assertIn("nobody was told", " ".join(logs.output))

    def test_the_health_row_still_records_the_failure(self):
        record_failure("writer", ModelUnavailable("no key"))
        self.assertTrue(AgentHealth.objects.get(agent="writer").is_failing)


class SendFailureTests(TestCase):
    def setUp(self):
        _holder("ops", "ops@example.com")

    def test_a_failed_send_is_recorded_rather_than_swallowed(self):
        """An alert nobody received is silence again by a different route."""
        from unittest.mock import patch

        with patch("brandtechsolution.mail.shell.EmailMultiAlternatives.send",
                   side_effect=RuntimeError("smtp is down")):
            sent = record_failure("writer", ModelUnavailable("no key"))

        self.assertFalse(sent)
        health = AgentHealth.objects.get(agent="writer")
        self.assertIn("smtp is down", health.last_alert_error)
        self.assertTrue(health.is_failing)

    def test_a_later_successful_send_clears_the_recorded_error(self):
        from unittest.mock import patch

        with patch("brandtechsolution.mail.shell.EmailMultiAlternatives.send",
                   side_effect=RuntimeError("smtp is down")):
            record_failure("writer", ModelUnavailable("no key"))

        record_failure("writer", AgentOutputInvalid("different failure"))
        self.assertEqual(AgentHealth.objects.get(agent="writer").last_alert_error, "")


class MailShellTests(TestCase):
    CONTEXT = {
        "subject": "Test", "agent": "writer", "accent": "#F87171",
        "error_class": "ModelUnavailable", "error_message": "no key",
        "started_at": "2026-09-21 18:40 EAT",
    }

    def test_css_is_inlined_and_no_style_block_survives(self):
        """Outlook and Gmail ignore <style>; an unstyled system mail looks broken."""
        html, _ = render_mail("mail/agent_alert.html", self.CONTEXT)
        self.assertIn("style=", html)
        self.assertNotIn("<style", html)

    def test_a_text_alternative_is_always_produced(self):
        _, text = render_mail("mail/agent_alert.html", self.CONTEXT)
        self.assertTrue(text.strip())
        self.assertIn("writer", text)
        self.assertNotIn("<", text)

    def test_a_sent_message_carries_both_halves(self):
        send_mail_html("Subject", "mail/agent_alert.html", self.CONTEXT,
                       ["ops@example.com"])

        message = mail.outbox[0]
        self.assertTrue(message.body.strip())                     # text
        self.assertEqual(message.alternatives[0][1], "text/html")  # html

    def test_no_recipients_does_not_send_or_raise(self):
        self.assertEqual(
            send_mail_html("Subject", "mail/agent_alert.html", self.CONTEXT, []), 0
        )
        self.assertEqual(mail.outbox, [])

    def test_the_layout_survives_rendering(self):
        """It is not run through nh3: these templates are ours, and sanitising
        would strip the table layout email clients need."""
        html, _ = render_mail("mail/agent_alert.html", self.CONTEXT)
        self.assertIn("<table", html)

    def test_a_recovery_reads_as_a_recovery(self):
        html, text = render_mail("mail/agent_alert.html",
                                 {**self.CONTEXT, "recovered": True})
        self.assertIn("working again", text)
        self.assertNotIn("ModelUnavailable", text)

    def test_the_footer_says_why_the_reader_got_it(self):
        _, text = render_mail("mail/agent_alert.html", self.CONTEXT)
        self.assertIn(ALERT_CAPABILITY, text)


class CapabilityTests(TestCase):
    def test_the_capability_is_declared_in_the_single_source_of_truth(self):
        from staff.capabilities import CODENAMES

        self.assertIn(ALERT_CAPABILITY, CODENAMES)

    def test_it_exists_as_a_real_permission(self):
        self.assertTrue(
            Permission.objects.filter(
                codename=ALERT_CAPABILITY, content_type__app_label="staff"
            ).exists()
        )
