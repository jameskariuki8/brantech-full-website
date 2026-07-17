from django.test import TestCase
from django.urls import reverse
from messaging.models import Suppression
from messaging.tokens import make_unsubscribe_token


class UnsubscribeTests(TestCase):
    def test_valid_token_adds_suppression(self):
        token = make_unsubscribe_token("bob@example.com")
        resp = self.client.get(reverse("unsubscribe", args=[token]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Suppression.objects.filter(email="bob@example.com").exists())

    def test_unsubscribe_is_idempotent(self):
        token = make_unsubscribe_token("bob@example.com")
        self.client.get(reverse("unsubscribe", args=[token]))
        self.client.get(reverse("unsubscribe", args=[token]))
        self.assertEqual(Suppression.objects.filter(email="bob@example.com").count(), 1)

    def test_tampered_token_is_rejected(self):
        resp = self.client.get(reverse("unsubscribe", args=["not-a-valid-token"]))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Suppression.objects.count(), 0)
