from unittest.mock import patch

import dns.resolver
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase

from messaging.models import Campaign, CampaignExclusion, CampaignRecipient, Inquiry, Suppression


class RecipientApiTestBase(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff", password="p", is_staff=True)
        self.client.force_login(self.staff)
        self.campaign = self._campaign()

    def _campaign(self, name="Launch", status="draft", total=0):
        return Campaign.objects.create(
            name=name, subject="S", body_source="<p>x</p>", body_html="<p>x</p>",
            status=status, total=total,
        )

    def _recipient(self, campaign=None, email="ada@example.com", **kwargs):
        return CampaignRecipient.objects.create(
            campaign=campaign or self.campaign, email=email, **kwargs
        )


class RecipientListTests(RecipientApiTestBase):
    def test_list_requires_a_campaign(self):
        resp = self.client.get("/api/messaging/recipients/")
        self.assertEqual(resp.status_code, 400)

    def test_list_rejects_a_non_numeric_campaign(self):
        resp = self.client.get("/api/messaging/recipients/?campaign=abc")
        self.assertEqual(resp.status_code, 400)

    def test_list_rejects_a_campaign_id_beyond_postgres_bigint_range(self):
        resp = self.client.get(
            "/api/messaging/recipients/?campaign=999999999999999999999999"
        )
        self.assertEqual(resp.status_code, 400)

    def test_list_rejects_a_non_ascii_digit_campaign(self):
        # str.isdigit() returns True for '²' (superscript two), which
        # int() cannot parse. This must return 400, not crash with a 500.
        resp = self.client.get("/api/messaging/recipients/?campaign=%C2%B2")
        self.assertEqual(resp.status_code, 400)

    def test_list_returns_only_that_campaigns_recipients(self):
        self._recipient(email="mine@example.com")
        other = self._campaign(name="Other")
        self._recipient(campaign=other, email="theirs@example.com")
        resp = self.client.get(f"/api/messaging/recipients/?campaign={self.campaign.id}")
        self.assertEqual(resp.status_code, 200)
        emails = [r["email"] for r in resp.json()["results"]]
        self.assertEqual(emails, ["mine@example.com"])

    def test_list_is_paginated(self):
        for i in range(55):
            self._recipient(email=f"user{i}@example.com")
        resp = self.client.get(f"/api/messaging/recipients/?campaign={self.campaign.id}")
        body = resp.json()
        self.assertEqual(body["count"], 55)
        self.assertEqual(len(body["results"]), 50)
        self.assertIsNotNone(body["next"])

    def test_search_matches_email(self):
        self._recipient(email="ada@example.com")
        self._recipient(email="bob@other.com")
        resp = self.client.get(
            f"/api/messaging/recipients/?campaign={self.campaign.id}&search=ADA"
        )
        emails = [r["email"] for r in resp.json()["results"]]
        self.assertEqual(emails, ["ada@example.com"])

    def test_search_matches_name(self):
        self._recipient(email="a@x.com", name="Ada Lovelace")
        self._recipient(email="b@x.com", name="Bob")
        resp = self.client.get(
            f"/api/messaging/recipients/?campaign={self.campaign.id}&search=lovelace"
        )
        emails = [r["email"] for r in resp.json()["results"]]
        self.assertEqual(emails, ["a@x.com"])

    def test_response_exposes_validation_status(self):
        self._recipient(validation_status="invalid_domain")
        resp = self.client.get(f"/api/messaging/recipients/?campaign={self.campaign.id}")
        self.assertEqual(resp.json()["results"][0]["validation_status"], "invalid_domain")

    def test_anonymous_cannot_list(self):
        self.client.logout()
        resp = self.client.get(f"/api/messaging/recipients/?campaign={self.campaign.id}")
        self.assertIn(resp.status_code, (401, 403))


class RecipientAddTests(RecipientApiTestBase):
    def _add(self, email, name="", campaign=None):
        return self.client.post(
            "/api/messaging/recipients/",
            data={
                "campaign": (campaign or self.campaign).id,
                "email": email,
                "name": name,
            },
            content_type="application/json",
        )

    def test_add_creates_a_pending_recipient(self):
        resp = self._add("ada@example.com", name="Ada")
        self.assertEqual(resp.status_code, 201)
        row = CampaignRecipient.objects.get(campaign=self.campaign)
        self.assertEqual(row.email, "ada@example.com")
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.validation_status, "valid")

    def test_add_normalises_case_and_whitespace(self):
        resp = self._add("  ADA@Example.COM  ")
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            CampaignRecipient.objects.filter(
                campaign=self.campaign, email="ada@example.com"
            ).exists()
        )

    def test_add_increments_campaign_total(self):
        self._add("ada@example.com")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.total, 1)

    def test_duplicate_within_campaign_is_rejected(self):
        self._add("ada@example.com")
        resp = self._add("ada@example.com")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(CampaignRecipient.objects.filter(campaign=self.campaign).count(), 1)

    def test_duplicate_check_is_case_insensitive(self):
        self._add("ada@example.com")
        resp = self._add("ADA@EXAMPLE.COM")
        self.assertEqual(resp.status_code, 400)

    def test_suppressed_address_is_rejected(self):
        Suppression.objects.create(email="ada@example.com")
        resp = self._add("ada@example.com")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(CampaignRecipient.objects.filter(campaign=self.campaign).exists())

    def test_malformed_address_is_rejected(self):
        # An address Django's own EmailField rejects never reaches the database.
        resp = self._add("not-an-email")
        self.assertEqual(resp.status_code, 400)

    def test_add_to_sending_campaign_is_allowed(self):
        sending = self._campaign(name="InFlight", status="sending")
        resp = self._add("ada@example.com", campaign=sending)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(CampaignRecipient.objects.get(campaign=sending).status, "pending")

    def test_add_to_paused_campaign_is_allowed(self):
        paused = self._campaign(name="Paused", status="paused")
        resp = self._add("ada@example.com", campaign=paused)
        self.assertEqual(resp.status_code, 201)

    def test_add_to_sent_campaign_is_rejected(self):
        finished = self._campaign(name="Done", status="sent")
        resp = self._add("ada@example.com", campaign=finished)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(CampaignRecipient.objects.filter(campaign=finished).exists())

    def test_add_to_failed_campaign_is_rejected(self):
        finished = self._campaign(name="Dead", status="failed")
        resp = self._add("ada@example.com", campaign=finished)
        self.assertEqual(resp.status_code, 400)

    def test_anonymous_cannot_add(self):
        self.client.logout()
        resp = self._add("ada@example.com")
        self.assertIn(resp.status_code, (401, 403))
        self.assertFalse(CampaignRecipient.objects.exists())

    def test_add_refuses_when_campaign_completes_before_insert_lands(self):
        # Simulates the race from the finding: `CampaignRecipientSerializer
        # .validate` checks the campaign's status before the insert, but
        # the outbox sender's `_maybe_complete` can flip the campaign to
        # "sent" between that check and the row actually landing (it only
        # scans queued/sending campaigns, so a `pending` row created after
        # would be stranded and never sent). Mutate the campaign's status
        # in the database from inside the serializer's own `create()` --
        # i.e. after validation passed but before `perform_create`'s
        # guarded increment runs -- to land in that exact window without
        # needing real threads.
        from unittest.mock import patch

        from messaging.serializers import CampaignRecipientSerializer

        original_create = CampaignRecipientSerializer.create

        def sneaky_create(self, validated_data):
            Campaign.objects.filter(pk=validated_data["campaign"].pk).update(status="sent")
            return original_create(self, validated_data)

        with patch.object(CampaignRecipientSerializer, "create", sneaky_create):
            resp = self._add("ada@example.com")

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(CampaignRecipient.objects.filter(campaign=self.campaign).exists())
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.total, 0)

    def test_adding_a_previously_excluded_address_clears_the_exclusion(self):
        # An explicit manual add is the admin overriding their earlier
        # removal, and it must win -- otherwise a removal can never be undone.
        CampaignExclusion.objects.create(campaign=self.campaign, email="ada@example.com")
        resp = self._add("ada@example.com")
        self.assertEqual(resp.status_code, 201)
        self.assertFalse(
            CampaignExclusion.objects.filter(
                campaign=self.campaign, email="ada@example.com"
            ).exists()
        )

    def test_clearing_the_exclusion_lets_a_later_rebuild_keep_the_address(self):
        from messaging import audience

        CampaignExclusion.objects.create(campaign=self.campaign, email="ada@example.com")
        self._add("ada@example.com")
        n = audience.build_recipients(self.campaign, [], ["ada@example.com"])
        self.assertEqual(n, 1)
        self.assertTrue(
            CampaignRecipient.objects.filter(
                campaign=self.campaign, email="ada@example.com"
            ).exists()
        )


class RecipientRemoveTests(RecipientApiTestBase):
    def _delete(self, recipient):
        return self.client.delete(f"/api/messaging/recipients/{recipient.id}/")

    def test_draft_removal_deletes_the_row(self):
        self.campaign.total = 1
        self.campaign.save(update_fields=["total"])
        row = self._recipient()
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(CampaignRecipient.objects.filter(pk=row.pk).exists())

    def test_draft_removal_decrements_total(self):
        self.campaign.total = 3
        self.campaign.save(update_fields=["total"])
        row = self._recipient()
        self._delete(row)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.total, 2)

    def test_total_never_goes_below_zero(self):
        # total is a PositiveIntegerField; an underflow would be a database error.
        row = self._recipient()
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 204)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.total, 0)

    def test_queued_removal_marks_skipped_and_keeps_total(self):
        campaign = self._campaign(name="Q", status="queued", total=1)
        row = self._recipient(campaign=campaign)
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 204)
        row.refresh_from_db()
        self.assertEqual(row.status, "skipped")
        campaign.refresh_from_db()
        self.assertEqual(campaign.total, 1)

    def test_sending_campaign_removal_marks_skipped(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign)
        self._delete(row)
        row.refresh_from_db()
        self.assertEqual(row.status, "skipped")

    def test_paused_campaign_removal_marks_skipped(self):
        campaign = self._campaign(name="P", status="paused", total=1)
        row = self._recipient(campaign=campaign)
        self._delete(row)
        row.refresh_from_db()
        self.assertEqual(row.status, "skipped")

    def test_already_sent_row_is_not_touched(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign, status="sent")
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 400)
        row.refresh_from_db()
        self.assertEqual(row.status, "sent")

    def test_in_flight_row_is_not_touched(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign, status="sending")
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 400)
        row.refresh_from_db()
        self.assertEqual(row.status, "sending")

    def test_failed_row_is_not_touched(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign, status="failed")
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 400)
        row.refresh_from_db()
        self.assertEqual(row.status, "failed")

    def test_removal_from_sent_campaign_is_rejected(self):
        campaign = self._campaign(name="Done", status="sent", total=1)
        row = self._recipient(campaign=campaign)
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(CampaignRecipient.objects.filter(pk=row.pk).exists())

    def test_removal_from_failed_campaign_is_rejected(self):
        campaign = self._campaign(name="Dead", status="failed", total=1)
        row = self._recipient(campaign=campaign)
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(CampaignRecipient.objects.filter(pk=row.pk).exists())

    def test_anonymous_cannot_remove(self):
        row = self._recipient()
        self.client.logout()
        resp = self._delete(row)
        self.assertIn(resp.status_code, (401, 403))
        self.assertTrue(CampaignRecipient.objects.filter(pk=row.pk).exists())

    def test_removal_refused_when_sender_claims_row_between_read_and_write(self):
        # Simulates the race from the finding: _remove_recipient is handed
        # an in-memory recipient object whose `.status` still reads
        # "pending" -- as it would have been read by get_object() earlier
        # in the request -- but the row in the database has since been
        # claimed by the outbox sender (marked "sending" with a
        # claim_token set) in order to dispatch it. The skip write must be
        # a guarded UPDATE keyed on the database's current status, not the
        # stale in-memory value, so it must not clobber the sender's claim
        # back to "skipped" and must refuse instead.
        import uuid

        from django.utils import timezone

        from messaging.api import _remove_recipient

        campaign = self._campaign(name="Q", status="queued", total=1)
        row = self._recipient(campaign=campaign)
        self.assertEqual(row.status, "pending")

        # Mutate the row in the database directly (bypassing `row`, the
        # in-memory object) to simulate the sender claiming it after the
        # object was constructed/read but before the skip write runs.
        CampaignRecipient.objects.filter(pk=row.pk).update(
            status="sending",
            claim_token=uuid.uuid4(),
            claimed_at=timezone.now(),
        )

        error = _remove_recipient(row)
        self.assertIsNotNone(error)
        self.assertIn("already being sent", error)

        row.refresh_from_db()
        self.assertEqual(row.status, "sending")
        self.assertIsNotNone(row.claim_token)

    def test_removing_an_already_skipped_recipient_is_idempotent(self):
        campaign = self._campaign(name="Q", status="queued", total=1)
        row = self._recipient(campaign=campaign, status="skipped")
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 204)
        row.refresh_from_db()
        self.assertEqual(row.status, "skipped")
        campaign.refresh_from_db()
        self.assertEqual(campaign.total, 1)

    def test_draft_removal_records_an_exclusion(self):
        row = self._recipient(email="ada@example.com")
        self._delete(row)
        self.assertTrue(
            CampaignExclusion.objects.filter(
                campaign=self.campaign, email="ada@example.com"
            ).exists()
        )

    def test_queued_removal_records_an_exclusion(self):
        campaign = self._campaign(name="Q", status="queued", total=1)
        row = self._recipient(campaign=campaign, email="ada@example.com")
        self._delete(row)
        self.assertTrue(
            CampaignExclusion.objects.filter(campaign=campaign, email="ada@example.com").exists()
        )

    def test_sending_removal_records_an_exclusion(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign, email="ada@example.com")
        self._delete(row)
        self.assertTrue(
            CampaignExclusion.objects.filter(campaign=campaign, email="ada@example.com").exists()
        )

    def test_paused_removal_records_an_exclusion(self):
        campaign = self._campaign(name="P", status="paused", total=1)
        row = self._recipient(campaign=campaign, email="ada@example.com")
        self._delete(row)
        self.assertTrue(
            CampaignExclusion.objects.filter(campaign=campaign, email="ada@example.com").exists()
        )

    def test_refused_removal_of_dispatched_row_records_no_exclusion(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign, email="ada@example.com", status="sent")
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(
            CampaignExclusion.objects.filter(campaign=campaign, email="ada@example.com").exists()
        )

    def test_refused_removal_from_sent_campaign_records_no_exclusion(self):
        campaign = self._campaign(name="Done", status="sent", total=1)
        row = self._recipient(campaign=campaign, email="ada@example.com")
        resp = self._delete(row)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(
            CampaignExclusion.objects.filter(campaign=campaign, email="ada@example.com").exists()
        )

    def test_removing_the_same_recipient_twice_does_not_raise(self):
        campaign = self._campaign(name="Q", status="queued", total=1)
        row = self._recipient(campaign=campaign, email="ada@example.com")
        resp1 = self._delete(row)
        self.assertEqual(resp1.status_code, 204)
        resp2 = self._delete(row)
        self.assertEqual(resp2.status_code, 204)
        self.assertEqual(
            CampaignExclusion.objects.filter(
                campaign=campaign, email="ada@example.com"
            ).count(),
            1,
        )


class RecipientValidateActionTests(RecipientApiTestBase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def _validate(self, campaign=None):
        return self.client.post(
            "/api/messaging/recipients/validate/",
            data={"campaign": (campaign or self.campaign).id},
            content_type="application/json",
        )

    def test_validate_returns_counts(self):
        self._recipient(email="ada@example.com")
        with patch("messaging.validation._query_mx", return_value=["mx1"]):
            resp = self._validate()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {"valid": 1, "invalid_syntax": 0, "invalid_domain": 0, "unknown": 0},
        )

    def test_validate_flags_a_dead_domain(self):
        row = self._recipient(email="ada@nope.invalid")
        with patch("messaging.validation._query_mx", side_effect=dns.resolver.NXDOMAIN):
            self._validate()
        row.refresh_from_db()
        self.assertEqual(row.validation_status, "invalid_domain")

    def test_validate_requires_a_campaign(self):
        resp = self.client.post(
            "/api/messaging/recipients/validate/", data={}, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_validate_rejects_an_unknown_campaign(self):
        resp = self.client.post(
            "/api/messaging/recipients/validate/",
            data={"campaign": 999999},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_validate_rejects_a_non_numeric_campaign_id_in_body(self):
        resp = self.client.post(
            "/api/messaging/recipients/validate/",
            data={"campaign": "abc"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_validate_rejects_an_out_of_range_campaign_id_in_body(self):
        resp = self.client.post(
            "/api/messaging/recipients/validate/",
            data={"campaign": 999999999999999999999999},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_validate_treats_campaign_zero_as_not_found_not_missing(self):
        # 0 is falsy but a present value -- must 404 (no such campaign), not
        # be reported as "A campaign id is required."
        resp = self.client.post(
            "/api/messaging/recipients/validate/",
            data={"campaign": 0},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_validate_rejects_a_sent_campaign(self):
        campaign = self._campaign(name="Done", status="sent")
        row = self._recipient(campaign=campaign)
        resp = self._validate(campaign)
        self.assertEqual(resp.status_code, 400)
        row.refresh_from_db()
        self.assertIsNone(row.validated_at)
        self.assertEqual(row.validation_status, "unknown")

    def test_validate_rejects_a_failed_campaign(self):
        campaign = self._campaign(name="Dead", status="failed")
        resp = self._validate(campaign)
        self.assertEqual(resp.status_code, 400)

    def test_anonymous_cannot_validate(self):
        self.client.logout()
        resp = self._validate()
        self.assertIn(resp.status_code, (401, 403))


class RecipientRemoveInvalidTests(RecipientApiTestBase):
    def _remove_invalid(self, campaign=None):
        return self.client.post(
            "/api/messaging/recipients/remove_invalid/",
            data={"campaign": (campaign or self.campaign).id},
            content_type="application/json",
        )

    def test_removes_only_flagged_rows(self):
        self.campaign.total = 3
        self.campaign.save(update_fields=["total"])
        good = self._recipient(email="ada@example.com", validation_status="valid")
        self._recipient(email="bad", validation_status="invalid_syntax")
        self._recipient(email="x@nope.invalid", validation_status="invalid_domain")

        resp = self._remove_invalid()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["removed"], 2)

        remaining = list(CampaignRecipient.objects.filter(campaign=self.campaign))
        self.assertEqual([r.pk for r in remaining], [good.pk])
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.total, 1)

    def test_unknown_rows_are_not_removed(self):
        # "unknown" means never checked -- not the same as known-bad.
        row = self._recipient(validation_status="unknown")
        resp = self._remove_invalid()
        self.assertEqual(resp.json()["removed"], 0)
        self.assertTrue(CampaignRecipient.objects.filter(pk=row.pk).exists())

    def test_sending_campaign_marks_flagged_rows_skipped(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign, email="x@nope.invalid",
                              validation_status="invalid_domain")
        resp = self._remove_invalid(campaign)
        self.assertEqual(resp.json()["removed"], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, "skipped")

    def test_dispatched_rows_are_reported_as_skipped_not_removed(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        row = self._recipient(campaign=campaign, email="x@nope.invalid",
                              status="sent", validation_status="invalid_domain")
        resp = self._remove_invalid(campaign)
        body = resp.json()
        self.assertEqual(body["removed"], 0)
        self.assertEqual(body["skipped"], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, "sent")

    def test_finished_campaign_is_rejected(self):
        campaign = self._campaign(name="Done", status="sent", total=1)
        row = self._recipient(campaign=campaign, validation_status="invalid_domain")
        resp = self._remove_invalid(campaign)
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(CampaignRecipient.objects.filter(pk=row.pk).exists())

    def test_other_campaigns_are_untouched(self):
        other = self._campaign(name="Other", total=1)
        stranger = self._recipient(campaign=other, email="x@nope.invalid",
                                   validation_status="invalid_domain")
        self._recipient(email="y@nope.invalid", validation_status="invalid_domain")
        self._remove_invalid()
        self.assertTrue(CampaignRecipient.objects.filter(pk=stranger.pk).exists())

    def test_anonymous_cannot_remove_invalid(self):
        self.client.logout()
        resp = self._remove_invalid()
        self.assertIn(resp.status_code, (401, 403))

    def test_rejects_a_non_numeric_campaign_id_in_body(self):
        resp = self.client.post(
            "/api/messaging/recipients/remove_invalid/",
            data={"campaign": "abc"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_rejects_an_out_of_range_campaign_id_in_body(self):
        resp = self.client.post(
            "/api/messaging/recipients/remove_invalid/",
            data={"campaign": 999999999999999999999999},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_treats_campaign_zero_as_not_found_not_missing(self):
        resp = self.client.post(
            "/api/messaging/recipients/remove_invalid/",
            data={"campaign": 0},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_total_never_goes_below_zero(self):
        # total is a PositiveIntegerField; the set-based rewrite must keep
        # the same underflow guard the per-row loop had.
        self._recipient(email="a@nope.invalid", validation_status="invalid_domain")
        self._recipient(email="b", validation_status="invalid_syntax")
        resp = self._remove_invalid()
        self.assertEqual(resp.json()["removed"], 2)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.total, 0)

    def test_already_skipped_flagged_row_in_active_campaign_counts_as_removed(self):
        # Removal is idempotent: a flagged row that's already `skipped`
        # (e.g. removed once already) is reported as removed again rather
        # than as skipped-refused.
        campaign = self._campaign(name="Q", status="queued", total=1)
        row = self._recipient(campaign=campaign, email="x@nope.invalid",
                              status="skipped", validation_status="invalid_domain")
        resp = self._remove_invalid(campaign)
        body = resp.json()
        self.assertEqual(body["removed"], 1)
        self.assertEqual(body["skipped"], 0)
        row.refresh_from_db()
        self.assertEqual(row.status, "skipped")

    def test_already_skipped_flagged_row_in_draft_campaign_is_deleted(self):
        # Draft eligibility includes rows already `skipped` -- there's no
        # in-flight send to protect in a draft campaign.
        self.campaign.total = 1
        self.campaign.save(update_fields=["total"])
        row = self._recipient(email="x@nope.invalid", status="skipped",
                              validation_status="invalid_domain")
        resp = self._remove_invalid()
        body = resp.json()
        self.assertEqual(body["removed"], 1)
        self.assertEqual(body["skipped"], 0)
        self.assertFalse(CampaignRecipient.objects.filter(pk=row.pk).exists())
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.total, 0)

    def test_mixed_flagged_and_dispatched_rows_report_correct_counts(self):
        # A single request covering every category at once: flagged+pending
        # (removed), flagged+dispatched (skipped, untouched), and unknown
        # (ignored entirely) -- exercising the set-based rewrite's queries
        # together rather than each in isolation.
        campaign = self._campaign(name="S", status="sending", total=3)
        pending_row = self._recipient(campaign=campaign, email="a@nope.invalid",
                                      validation_status="invalid_domain")
        sent_row = self._recipient(campaign=campaign, email="bad-syntax",
                                   status="sent", validation_status="invalid_syntax")
        unknown_row = self._recipient(campaign=campaign, email="c@example.com",
                                      validation_status="unknown")
        resp = self._remove_invalid(campaign)
        body = resp.json()
        self.assertEqual(body["removed"], 1)
        self.assertEqual(body["skipped"], 1)
        pending_row.refresh_from_db()
        self.assertEqual(pending_row.status, "skipped")
        sent_row.refresh_from_db()
        self.assertEqual(sent_row.status, "sent")
        unknown_row.refresh_from_db()
        self.assertEqual(unknown_row.status, "pending")
        campaign.refresh_from_db()
        self.assertEqual(campaign.total, 3)

    def test_records_exclusions_for_removed_rows_in_a_draft_campaign(self):
        self.campaign.total = 1
        self.campaign.save(update_fields=["total"])
        self._recipient(email="bad@example.com", validation_status="invalid_syntax")
        self._remove_invalid()
        self.assertTrue(
            CampaignExclusion.objects.filter(
                campaign=self.campaign, email="bad@example.com"
            ).exists()
        )

    def test_records_exclusions_for_rows_marked_skipped_in_an_active_campaign(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        self._recipient(campaign=campaign, email="x@nope.invalid",
                        validation_status="invalid_domain")
        self._remove_invalid(campaign)
        self.assertTrue(
            CampaignExclusion.objects.filter(
                campaign=campaign, email="x@nope.invalid"
            ).exists()
        )

    def test_does_not_record_an_exclusion_for_a_dispatched_row(self):
        campaign = self._campaign(name="S", status="sending", total=1)
        self._recipient(campaign=campaign, email="x@nope.invalid", status="sent",
                        validation_status="invalid_domain")
        self._remove_invalid(campaign)
        self.assertFalse(
            CampaignExclusion.objects.filter(
                campaign=campaign, email="x@nope.invalid"
            ).exists()
        )

    def test_a_rebuild_does_not_resurrect_rows_removed_by_remove_invalid(self):
        from messaging import audience

        self.campaign.total = 1
        self.campaign.save(update_fields=["total"])
        self._recipient(email="bad@example.com", validation_status="invalid_syntax")
        self._remove_invalid()

        n = audience.build_recipients(self.campaign, [], ["bad@example.com"])
        self.assertEqual(n, 0)
        self.assertFalse(
            CampaignRecipient.objects.filter(
                campaign=self.campaign, email="bad@example.com"
            ).exists()
        )


class RecipientRemovalPersistsAcrossRebuildTests(RecipientApiTestBase):
    """The exact scenario from the review: build, remove, rebuild -- the
    removed address must not silently come back."""

    def _build(self, campaign=None, sources=None, manual=None):
        return self.client.post(
            f"/api/messaging/campaigns/{(campaign or self.campaign).id}/build_recipients/",
            data={"sources": sources or [], "manual_emails": manual or []},
            content_type="application/json",
        )

    def test_removed_recipient_stays_removed_after_rebuild_with_extra_manual_address(self):
        Inquiry.objects.create(name="N1", email="n1@x.com", message="m")
        resp = self._build(sources=["inquiries"])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

        row = CampaignRecipient.objects.get(campaign=self.campaign, email="n1@x.com")
        del_resp = self.client.delete(f"/api/messaging/recipients/{row.id}/")
        self.assertEqual(del_resp.status_code, 204)

        resp = self._build(sources=["inquiries"], manual=["n2@x.com"])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.total, 1)
        emails = set(
            CampaignRecipient.objects.filter(campaign=self.campaign)
            .values_list("email", flat=True)
        )
        self.assertEqual(emails, {"n2@x.com"})
