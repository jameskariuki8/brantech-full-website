from django.test import TestCase, Client
from django.urls import reverse
from messaging.models import InboundEmail, Inquiry


class MailgunInboundWebhookTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.webhook_url = reverse("mailgun_inbound_webhook")

    def test_inbound_webhook_creates_records(self):
        payload = {
            "sender": "John Doe <john.doe@example.com>",
            "recipient": "contact@teklora.co.ke",
            "subject": "Inquiry about Cloud Consulting",
            "stripped-text": "Hello Teklora team, we need help migrating our servers.",
            "stripped-html": "<p>Hello Teklora team, we need help migrating our servers.</p>",
            "timestamp": "1722898000",
            "token": "test-token-123",
            "signature": "test-sig-123",
        }

        response = self.client.post(self.webhook_url, payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))

        # Verify InboundEmail record was saved
        inbound = InboundEmail.objects.get(pk=data["inbound_id"])
        self.assertEqual(inbound.sender, "john.doe@example.com")
        self.assertEqual(inbound.recipient, "contact@teklora.co.ke")
        self.assertEqual(inbound.subject, "Inquiry about Cloud Consulting")
        self.assertIn("Hello Teklora team", inbound.body_plain)

        # Verify Inquiry record was saved for administrative dashboard
        inquiry = Inquiry.objects.get(pk=data["inquiry_id"])
        self.assertEqual(inquiry.name, "John Doe")
        self.assertEqual(inquiry.email, "john.doe@example.com")
        self.assertIn("Inquiry about Cloud Consulting", inquiry.message)

    def test_invalid_signature_returns_406(self):
        payload = {
            "sender": "attacker@example.com",
            "recipient": "contact@teklora.co.ke",
            "subject": "Spoofed Request",
            "stripped-text": "Malicious payload",
            "timestamp": "1722898000",
            "token": "test-token",
            "signature": "invalid-hmac-signature",
        }
        with self.settings(MAILGUN_WEBHOOK_SIGNING_KEY="real-secret-key", TESTING=False):
            response = self.client.post(self.webhook_url, payload)
            self.assertEqual(response.status_code, 406)
            data = response.json()
            self.assertFalse(data.get("ok"))
            self.assertEqual(data.get("error"), "Invalid signature")

    def test_valid_hmac_signature_and_replay_protection(self):
        import hmac
        import hashlib
        import time

        key = "secret-signing-key"
        timestamp = str(int(time.time()))
        token = "unique-test-token-999"
        sig = hmac.new(key.encode("utf-8"), f"{timestamp}{token}".encode("utf-8"), hashlib.sha256).hexdigest()

        payload = {
            "sender": "Alice <alice@example.com>",
            "recipient": "contact@teklora.co.ke",
            "subject": "Valid Signature",
            "stripped-text": "Hello world",
            "timestamp": timestamp,
            "token": token,
            "signature": sig,
        }

        with self.settings(MAILGUN_WEBHOOK_SIGNING_KEY=key, TESTING=False):
            # First request should succeed (200)
            res1 = self.client.post(self.webhook_url, payload)
            self.assertEqual(res1.status_code, 200)

            # Replay of the exact same request should be rejected (406)
            res2 = self.client.post(self.webhook_url, payload)
            self.assertEqual(res2.status_code, 406)

    def test_subaccount_parent_signature(self):
        import hmac
        import hashlib
        import time

        key = "parent-signing-key"
        timestamp = str(int(time.time()))
        token = "subaccount-token-888"
        parent_sig = hmac.new(key.encode("utf-8"), f"{timestamp}{token}".encode("utf-8"), hashlib.sha256).hexdigest()

        payload = {
            "sender": "Subaccount Sender <sub@example.com>",
            "recipient": "contact@teklora.co.ke",
            "subject": "Subaccount Message",
            "stripped-text": "Sent via subaccount",
            "timestamp": timestamp,
            "token": token,
            "signature": "subaccount-specific-sig",
            "parent-signature": parent_sig,
        }

        with self.settings(MAILGUN_WEBHOOK_SIGNING_KEY=key, TESTING=False):
            res = self.client.post(self.webhook_url, payload)
            self.assertEqual(res.status_code, 200)

    def test_timestamp_freshness_expired(self):
        import hmac
        import hashlib

        key = "secret-signing-key"
        old_timestamp = "1000000000"  # Far in the past
        token = "stale-token-777"
        sig = hmac.new(key.encode("utf-8"), f"{old_timestamp}{token}".encode("utf-8"), hashlib.sha256).hexdigest()

        payload = {
            "sender": "Old Sender <old@example.com>",
            "recipient": "contact@teklora.co.ke",
            "subject": "Old Message",
            "stripped-text": "Expired message",
            "timestamp": old_timestamp,
            "token": token,
            "signature": sig,
        }

        with self.settings(MAILGUN_WEBHOOK_SIGNING_KEY=key, TESTING=False):
            res = self.client.post(self.webhook_url, payload)
            self.assertEqual(res.status_code, 406)
