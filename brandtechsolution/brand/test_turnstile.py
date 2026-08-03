"""Bot protection on the public write endpoints.

The rule these pin down: verification happens on the SERVER. A bot never
loads the page, so the widget is irrelevant to it - only the token check on
the endpoint stands between a script and the database.
"""
import json
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from appointments.models import Appointment
from brand.models import BlogComment, BlogPost
from brandtechsolution import turnstile
from messaging.models import Inquiry

ENABLED = override_settings(
    TURNSTILE_SECRET_KEY="test-secret", TURNSTILE_SITE_KEY="test-site"
)
DISABLED = override_settings(TURNSTILE_SECRET_KEY="", TURNSTILE_SITE_KEY="")


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def cloudflare_says(payload):
    return patch(
        "brandtechsolution.turnstile.urllib.request.urlopen",
        return_value=FakeResponse(payload),
    )


def cloudflare_unreachable():
    return patch(
        "brandtechsolution.turnstile.urllib.request.urlopen",
        side_effect=OSError("connection refused"),
    )


class VerificationTest(TestCase):
    @DISABLED
    def test_unconfigured_keys_disable_the_check(self):
        """Local development and the test suite run without credentials."""
        self.assertFalse(turnstile.is_enabled())

    @ENABLED
    def test_an_absent_token_never_calls_cloudflare(self):
        with patch("brandtechsolution.turnstile.urllib.request.urlopen") as opened:
            self.assertFalse(turnstile.verify(""))
        opened.assert_not_called()

    @ENABLED
    def test_a_token_cloudflare_accepts_passes(self):
        with cloudflare_says({"success": True}):
            self.assertTrue(turnstile.verify("a-token"))

    @ENABLED
    def test_a_token_cloudflare_rejects_fails(self):
        with cloudflare_says({"success": False, "error-codes": ["invalid-input-response"]}):
            self.assertFalse(turnstile.verify("a-token"))

    @ENABLED
    def test_it_fails_closed_when_cloudflare_is_unreachable(self):
        """"The verifier is down" and "this is a bot" look identical from
        here, so the submission is refused rather than waved through."""
        with cloudflare_unreachable():
            self.assertFalse(turnstile.verify("a-token"))

    @ENABLED
    def test_a_malformed_response_fails_closed(self):
        with patch(
            "brandtechsolution.turnstile.urllib.request.urlopen",
            return_value=FakeResponse("not-a-dict"),
        ):
            self.assertFalse(turnstile.verify("a-token"))


@ENABLED
class EndpointsRefuseUnverifiedPostsTest(TestCase):
    """Every public endpoint that writes, with no token supplied."""

    def setUp(self):
        self.post = BlogPost.objects.create(
            title="A post", slug="a-post", content="body", status="published"
        )

    def test_appointment_booking_is_refused(self):
        response = self.client.post(
            "/appointments/create/",
            json.dumps({
                "email": "bot@example.com", "full_name": "Bot",
                "date": str(date.today() + timedelta(days=2)), "time": "10:00",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_signup_is_refused(self):
        response = self.client.post("/signup/", {
            "firstName": "Bot", "lastName": "Net",
            "email": "bot@example.com",
            "password": "s3cure-passphrase!", "confirmPassword": "s3cure-passphrase!",
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="bot@example.com").exists())

    def test_blog_comment_is_refused(self):
        response = self.client.post(
            f"/api/blogs/{self.post.pk}/comment/",
            json.dumps({"browser_id": "abc", "user_name": "Bot", "content": "buy things"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(BlogComment.objects.count(), 0)

    def test_contact_form_is_refused(self):
        response = self.client.post("/contacts/submit/", {
            "name": "Bot", "email": "bot@example.com", "message": "buy things",
        })

        self.assertIn(response.status_code, (302, 400))
        self.assertEqual(Inquiry.objects.count(), 0)


@ENABLED
class EndpointsAcceptVerifiedPostsTest(TestCase):
    """The same endpoints with a token Cloudflare accepts - so the tests
    above are proving the gate, not a broken endpoint."""

    def test_a_verified_booking_is_created(self):
        with cloudflare_says({"success": True}):
            response = self.client.post(
                "/appointments/create/",
                json.dumps({
                    "email": "real@example.com", "full_name": "A Client",
                    "date": str(date.today() + timedelta(days=2)), "time": "10:00",
                    "cf-turnstile-response": "a-token",
                }),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_a_verified_contact_message_is_saved(self):
        with cloudflare_says({"success": True}):
            self.client.post("/contacts/submit/", {
                "name": "A Client", "email": "real@example.com",
                "message": "Hello there", "cf-turnstile-response": "a-token",
            })

        self.assertEqual(Inquiry.objects.count(), 1)


class ProductionGuardTest(TestCase):
    """The likeliest failure is deploying with the env vars missing, which
    looks exactly like working software.

    Every case overrides TESTING=False. The check exempts the test suite -
    Django's runner forces DEBUG=False, so without that exemption this guard
    aborts every test run - and these tests are asserting what happens in
    real production, so they have to switch the exemption off.
    """

    @override_settings(DEBUG=False, TESTING=False, TURNSTILE_SECRET_KEY="")
    def test_unconfigured_production_is_a_startup_error(self):
        errors = turnstile.check_configured_in_production(None)

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "turnstile.E001")

    @override_settings(DEBUG=False, TESTING=False, TURNSTILE_SECRET_KEY="set")
    def test_configured_production_is_fine(self):
        self.assertEqual(turnstile.check_configured_in_production(None), [])

    @override_settings(DEBUG=True, TESTING=False, TURNSTILE_SECRET_KEY="")
    def test_debug_may_run_without_keys(self):
        self.assertEqual(turnstile.check_configured_in_production(None), [])

    @override_settings(DEBUG=False, TESTING=True, TURNSTILE_SECRET_KEY="")
    def test_the_test_suite_is_exempt(self):
        """Pins the exemption itself - removing it silently breaks every
        other test in the project, which is a confusing way to find out."""
        self.assertEqual(turnstile.check_configured_in_production(None), [])
