"""Contacts fill themselves, group into segments, and feed campaign audiences."""

import datetime
import json

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from appointments.models import Appointment
from messaging.models import (
    BlockedSender, Campaign, Contact, EmailTemplate, Inquiry, Segment, Suppression,
)
from messaging.tests import grant_all_capabilities


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class ContactCaptureTests(TestCase):
    def test_inquiry_adds_a_contact_and_later_ones_only_fill_blanks(self):
        Inquiry.objects.create(name="", email="Ann@Example.com", message="hi")
        Inquiry.objects.create(name="Ann Mwangi", email="ann@example.com", phone="0712", message="again")
        contact = Contact.objects.get()
        self.assertEqual(contact.email, "ann@example.com")
        self.assertEqual(contact.name, "Ann Mwangi")
        self.assertEqual(contact.source, "inquiry")

        contact.name = "Ann (edited)"
        contact.save()
        Inquiry.objects.create(name="Someone Else", email="ann@example.com", message="third")
        contact.refresh_from_db()
        self.assertEqual(contact.name, "Ann (edited)")

    def test_booking_and_customer_account_add_contacts(self):
        Appointment.objects.create(
            email="bob@example.com", full_name="Bob", title="Call", description="d",
            date=datetime.date(2026, 10, 1), time=datetime.time(10), estimated_duration=30,
        )
        User.objects.create_user("carol", email="carol@example.com", first_name="Carol")
        self.assertEqual(
            dict(Contact.objects.values_list("email", "source")),
            {"bob@example.com": "appointment", "carol@example.com": "account"},
        )

    def test_staff_own_addresses_and_spam_senders_are_not_kept(self):
        User.objects.create_user("st", email="st@example.com", is_staff=True)
        Inquiry.objects.create(name="Us", email="info@teklora.co.ke", message="m")
        BlockedSender.objects.create(email="spam@bad.com")
        Inquiry.objects.create(name="Spam", email="spam@bad.com", message="m")
        self.assertFalse(Contact.objects.exists())


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class ContactApiTests(TestCase):
    def setUp(self):
        self.user = grant_all_capabilities(User.objects.create_user("ada", password="p", is_staff=True))
        self.client.force_login(self.user)
        self.clients = Segment.objects.create(name="Clients")
        self.leads = Segment.objects.create(name="Leads")

    def _post(self, url, data):
        return self.client.post(url, data=json.dumps(data), content_type="application/json")

    def test_create_lowercases_and_rejects_a_duplicate_in_another_case(self):
        resp = self._post("/api/messaging/contacts/", {"email": "New@Example.com", "segments": [self.clients.pk]})
        self.assertEqual(resp.status_code, 201, resp.content)
        contact = Contact.objects.get()
        self.assertEqual((contact.email, contact.source), ("new@example.com", "manual"))
        self.assertEqual(list(contact.segments.all()), [self.clients])
        resp = self._post("/api/messaging/contacts/", {"email": "NEW@example.com"})
        self.assertEqual(resp.status_code, 400)

    def test_list_filters_by_segment_and_shows_status(self):
        a = Contact.objects.create(email="a@example.com")
        Contact.objects.create(email="b@example.com")
        a.segments.add(self.clients)
        Suppression.objects.create(email="a@example.com", reason="unsubscribed")
        data = self.client.get(f"/api/messaging/contacts/?segment={self.clients.pk}").json()
        self.assertEqual([r["email"] for r in data["results"]], ["a@example.com"])
        self.assertEqual(data["results"][0]["status_label"], "Unsubscribed")
        data = self.client.get("/api/messaging/contacts/?segment=none").json()
        self.assertEqual([r["email"] for r in data["results"]], ["b@example.com"])

    def test_bulk_add_to_segment_for_everything_matching_a_search(self):
        for e in ("x1@acme.com", "x2@acme.com", "y@other.com"):
            Contact.objects.create(email=e)
        resp = self._post("/api/messaging/contacts/bulk/", {
            "action": "add_segment", "segment": self.leads.pk,
            "all_matching": True, "filters": {"q": "acme"},
        })
        self.assertEqual(resp.json()["count"], 2)
        self.assertEqual(self.leads.contacts.count(), 2)

    def test_staff_can_undo_their_own_stop_but_not_a_real_unsubscribe(self):
        a = Contact.objects.create(email="a@example.com")
        b = Contact.objects.create(email="b@example.com")
        Suppression.objects.create(email="b@example.com", reason="unsubscribed")
        self._post("/api/messaging/contacts/bulk/", {"action": "unsubscribe", "ids": [a.pk, b.pk]})
        self.assertEqual(Suppression.objects.get(email="a@example.com").reason, "manual")
        self._post("/api/messaging/contacts/bulk/", {"action": "resubscribe", "ids": [a.pk, b.pk]})
        self.assertEqual(list(Suppression.objects.values_list("email", flat=True)), ["b@example.com"])

    def test_csv_import_brings_names_into_a_new_segment(self):
        Contact.objects.create(email="old@example.com", name="Kept")
        csv = (
            "First name,Last name,Email,Company\n"
            "Jane,Doe,jane@example.com,Acme\n"
            "Other,Name,OLD@example.com,\n"
            "Us,,info@teklora.co.ke,\n"
        ).encode()
        resp = self.client.post("/api/messaging/contacts/import/", {
            "file": SimpleUploadedFile("people.csv", csv, content_type="text/csv"),
            "new_segment": "Expo leads",
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json(), {"created": 1, "existing": 1, "skipped": 1})
        jane = Contact.objects.get(email="jane@example.com")
        self.assertEqual((jane.name, jane.company, jane.source), ("Jane Doe", "Acme", "import"))
        self.assertEqual(Contact.objects.get(email="old@example.com").name, "Kept")
        self.assertEqual(Segment.objects.get(name="Expo leads").contacts.count(), 2)

    def test_pasted_import(self):
        resp = self._post("/api/messaging/contacts/import/", {
            "text": "p@example.com, q@example.com", "segments": [self.leads.pk],
        })
        self.assertEqual(resp.json()["created"], 2)
        self.assertEqual(self.leads.contacts.count(), 2)

    def test_deleting_a_segment_keeps_its_contacts(self):
        Contact.objects.create(email="a@example.com").segments.add(self.clients)
        self.assertEqual(self.client.delete(f"/api/messaging/segments/{self.clients.pk}/").status_code, 204)
        self.assertTrue(Contact.objects.filter(email="a@example.com").exists())

    def test_contacts_need_the_recipients_capability(self):
        other = User.objects.create_user("bo", password="p", is_staff=True)
        self.client.force_login(other)
        self.assertEqual(self.client.get("/api/messaging/contacts/").status_code, 403)


@override_settings(MAILBOX_DOMAIN="teklora.co.ke")
class SegmentAudienceTests(TestCase):
    def setUp(self):
        self.user = grant_all_capabilities(User.objects.create_user("ada", password="p", is_staff=True))
        self.client.force_login(self.user)
        template = EmailTemplate.objects.create(name="T", subject="S", body_source="<p>x</p>", body_html="<p>x</p>")
        self.campaign = Campaign.objects.create(name="c", template=template, subject="S", body_html="<p>x</p>")
        self.clients = Segment.objects.create(name="Clients")
        self.leads = Segment.objects.create(name="Leads")
        for email, segs in (
            ("a@example.com", [self.clients]),
            ("b@example.com", [self.clients, self.leads]),
            ("gone@example.com", [self.clients]),
            ("lead@example.com", [self.leads]),
        ):
            Contact.objects.create(email=email).segments.add(*segs)
        Suppression.objects.create(email="gone@example.com", reason="bounced")

    def _build(self, body):
        return self.client.post(
            f"/api/messaging/campaigns/{self.campaign.pk}/build_recipients/",
            data=json.dumps(body), content_type="application/json",
        )

    def test_segments_build_the_audience_without_suppressed_or_duplicates(self):
        resp = self._build({"segments": [self.clients.pk]})
        self.assertEqual(resp.json()["count"], 2)
        self._build({"segments": [self.leads.pk]})
        self.campaign.refresh_from_db()
        self.assertEqual(
            set(self.campaign.recipients.values_list("email", flat=True)),
            {"a@example.com", "b@example.com", "lead@example.com"},
        )
        self.assertEqual(self.campaign.audience, ["Clients", "Leads"])

    def test_everyone(self):
        self.assertEqual(self._build({"everyone": True}).json()["count"], 3)

    def test_overview_counts_reachable_people_per_segment(self):
        data = self.client.get("/api/messaging/campaigns/overview/").json()["audience"]
        self.assertEqual(data["everyone"], 3)
        self.assertEqual({s["name"]: s["count"] for s in data["segments"]}, {"Clients": 2, "Leads": 2})
