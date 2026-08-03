"""The public booking endpoint.

/appointments/create/ is unauthenticated and CSRF-exempt by design - it is
the website's booking form. That makes everything it accepts untrusted, and
it used to trust two things it should not have: the email address as proof of
identity, and the status field as a workflow decision.
"""
import json
from datetime import date, time, timedelta

from django.test import Client, TestCase

from .models import Appointment

URL = "/appointments/create/"


def booking(**overrides):
    payload = {
        "email": "client@example.com",
        "full_name": "A Client",
        "phone": "+254700000001",
        "title": "Strategy Consultation",
        "description": "First session",
        "date": str(date.today() + timedelta(days=3)),
        "time": "10:00",
        "estimated_duration": 30,
    }
    payload.update(overrides)
    return payload


class RepeatBookingTest(TestCase):
    def setUp(self):
        self.client = Client()

    def _book(self, **overrides):
        return self.client.post(
            URL, json.dumps(booking(**overrides)), content_type="application/json"
        )

    def test_a_second_booking_from_one_address_creates_a_second_row(self):
        """The behaviour the unique constraint used to make impossible."""
        self.assertEqual(self._book(description="First").status_code, 201)
        self.assertEqual(self._book(description="Second").status_code, 201)

        rows = Appointment.objects.filter(email="client@example.com")
        self.assertEqual(rows.count(), 2)
        self.assertEqual(
            sorted(r.description for r in rows), ["First", "Second"]
        )

    def test_a_stranger_cannot_rewrite_an_existing_booking(self):
        """The finding. Submitting someone else's address used to UPDATE
        their appointment - moving its date, title and notes."""
        self._book(description="Real client's session", title="Real topic")
        original = Appointment.objects.get(email="client@example.com")

        self._book(
            description="Attacker's text",
            title="Moved",
            date=str(date.today() + timedelta(days=90)),
        )

        original.refresh_from_db()
        self.assertEqual(original.description, "Real client's session")
        self.assertEqual(original.title, "Real topic")
        self.assertEqual(Appointment.objects.count(), 2)

    def test_two_people_may_share_a_phone_number(self):
        self.assertEqual(self._book(email="a@example.com").status_code, 201)
        self.assertEqual(self._book(email="b@example.com").status_code, 201)

        self.assertEqual(Appointment.objects.count(), 2)


class UntrustedInputTest(TestCase):
    def setUp(self):
        self.client = Client()

    def _book(self, **overrides):
        return self.client.post(
            URL, json.dumps(booking(**overrides)), content_type="application/json"
        )

    def test_a_caller_cannot_confirm_their_own_booking(self):
        """status came straight from the request body, so anyone could send
        "confirmed" and appear to staff as already agreed."""
        self._book(status="confirmed")

        self.assertEqual(Appointment.objects.get().status, "pending")

    def test_a_caller_cannot_set_any_other_status(self):
        for attempt in ("completed", "cancelled", "rescheduled"):
            with self.subTest(status=attempt):
                Appointment.objects.all().delete()
                self._book(status=attempt)
                self.assertEqual(Appointment.objects.get().status, "pending")

    def test_a_missing_phone_is_stored_empty_not_invented(self):
        """It used to synthesise a +2547XXXXXXXX number to satisfy the unique
        constraint, putting fake contact details in front of staff."""
        self._book(phone="")

        self.assertEqual(Appointment.objects.get().phone, "")

    def test_required_fields_are_still_enforced(self):
        for missing in ("email", "date", "time"):
            with self.subTest(missing=missing):
                response = self._book(**{missing: ""})
                self.assertEqual(response.status_code, 400)

    def test_errors_do_not_leak_database_detail(self):
        response = self.client.post(
            URL, "not json at all", content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        body = response.json()
        for leak in ("appointments_appointment", "DETAIL", "psycopg", "Traceback"):
            self.assertNotIn(leak, json.dumps(body))
