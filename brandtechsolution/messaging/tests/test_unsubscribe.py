from django.test import TestCase
from django.urls import reverse
from messaging.models import Suppression
from messaging.tokens import make_unsubscribe_token


class UnsubscribeTests(TestCase):
    def test_get_valid_token_shows_confirmation_without_mutating(self):
        token = make_unsubscribe_token("bob@example.com")
        resp = self.client.get(reverse("unsubscribe", args=[token]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Suppression.objects.filter(email="bob@example.com").exists())

    def test_post_valid_token_adds_suppression(self):
        token = make_unsubscribe_token("bob@example.com")
        resp = self.client.post(reverse("unsubscribe", args=[token]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Suppression.objects.filter(email="bob@example.com").exists())

    def test_post_unsubscribe_is_idempotent(self):
        token = make_unsubscribe_token("bob@example.com")
        self.client.post(reverse("unsubscribe", args=[token]))
        self.client.post(reverse("unsubscribe", args=[token]))
        self.assertEqual(Suppression.objects.filter(email="bob@example.com").count(), 1)

    def test_get_tampered_token_is_rejected(self):
        resp = self.client.get(reverse("unsubscribe", args=["not-a-valid-token"]))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Suppression.objects.count(), 0)

    def test_post_tampered_token_is_rejected(self):
        resp = self.client.post(reverse("unsubscribe", args=["not-a-valid-token"]))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Suppression.objects.count(), 0)
