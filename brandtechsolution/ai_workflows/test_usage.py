"""What each call consumed, what it cost, and what the ceiling does about it.

`BudgetExceeded` was named for a budget that did not exist: the only ceiling in
the harness counted *dispatches*, so one agent making forty long calls inside a
single dispatch read as one dispatch. These tests are mostly about the three
ways a total can be wrong -- unpriced, unmeasured, and double-counted -- because
a spend report that quietly rounds the unknown parts to zero is worse than no
report at all.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from ai_workflows.harness import usage
from ai_workflows.harness.usage import Ledger, Usage
from ai_workflows.models import CatalogueEntry, ModelInvocation


class _Response:
    """Stands in for an AIMessage, carrying only what accounting reads."""

    def __init__(self, usage_metadata=None, response_metadata=None):
        self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata or {}


# The shape a live gemini-2.5-flash call actually returns, copied from a probe
# rather than imagined -- guessing this is how the structured-output path came
# to report nothing at all.
LIVE_SHAPE = {
    "input_tokens": 13,
    "output_tokens": 140,
    "total_tokens": 153,
    "input_token_details": {"cache_read": 0},
    "output_token_details": {"reasoning": 115},
}


class UsageExtractionTests(TestCase):

    def test_it_reads_the_shape_a_real_response_carries(self):
        measured = usage.usage_of(_Response(LIVE_SHAPE))
        self.assertEqual(measured.prompt_tokens, 13)
        self.assertEqual(measured.completion_tokens, 140)
        self.assertEqual(measured.total_tokens, 153)

    def test_reasoning_tokens_are_kept_separate(self):
        """82% of that probe's billed output was reasoning nobody ever sees.

        Rolled into one number, a bill dominated by it is inexplicable.
        """
        self.assertEqual(usage.usage_of(_Response(LIVE_SHAPE)).reasoning_tokens, 115)

    def test_a_response_reporting_nothing_is_none_not_zero(self):
        # A zeroed row would be indistinguishable from a free call.
        self.assertIsNone(usage.usage_of(_Response(None)))
        self.assertIsNone(usage.usage_of(_Response({})))
        self.assertIsNone(usage.usage_of(None))

    def test_the_older_per_vendor_shape_is_still_read(self):
        measured = usage.usage_of(_Response(
            None, {"token_usage": {"prompt_tokens": 5, "completion_tokens": 7}},
        ))
        self.assertEqual((measured.prompt_tokens, measured.completion_tokens), (5, 7))
        self.assertEqual(measured.total_tokens, 12)

    def test_a_total_is_derived_when_the_provider_omits_it(self):
        measured = usage.usage_of(_Response({"input_tokens": 3, "output_tokens": 4}))
        self.assertEqual(measured.total_tokens, 7)

    def test_the_model_that_answered_wins_over_the_one_requested(self):
        # An alias resolves to a dated snapshot, and the one that bills is the
        # one that answered.
        response = _Response(LIVE_SHAPE, {"model_name": "gemini-2.5-flash-002"})
        self.assertEqual(usage.model_name_of(response, "gemini-2.5-flash"),
                         "gemini-2.5-flash-002")

    def test_the_requested_model_is_used_when_none_is_reported(self):
        self.assertEqual(usage.model_name_of(_Response(LIVE_SHAPE), "asked-for"),
                         "asked-for")


class PricingTests(TestCase):

    def setUp(self):
        # Stored with the prefix the listing endpoint returns.
        self.entry = CatalogueEntry.objects.create(
            provider="gemini", model_id="models/gemini-2.5-flash",
            input_price_per_mtok=Decimal("0.30"),
            output_price_per_mtok=Decimal("2.50"),
            price_source=CatalogueEntry.OPENROUTER,
        )

    def test_the_prefix_gemini_listings_carry_is_normalised_away(self):
        self.assertEqual(usage.normalise_model_id("models/gemini-2.5-flash"),
                         "gemini-2.5-flash")
        self.assertEqual(usage.normalise_model_id("gemini-2.5-flash"),
                         "gemini-2.5-flash")

    def test_a_price_is_found_from_the_spelling_the_client_uses(self):
        """The catalogue stores `models/x`; the client is built with `x`.

        Matching the raw string misses, and a miss is silent -- it reads as
        "this model has no price", which is indistinguishable from one that
        genuinely has none.
        """
        self.assertEqual(usage.price_for("gemini", "gemini-2.5-flash"), self.entry)
        self.assertEqual(usage.price_for("gemini", "models/gemini-2.5-flash"),
                         self.entry)

    def test_an_unknown_model_has_no_price_rather_than_a_zero_one(self):
        cost, source = usage.cost_of(Usage(100, 100, 200), "gemini", "never-heard-of-it")
        self.assertIsNone(cost)
        self.assertEqual(source, "")

    def test_a_known_model_is_priced_from_the_catalogue(self):
        cost, source = usage.cost_of(
            Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000),
            "gemini", "gemini-2.5-flash",
        )
        self.assertAlmostEqual(cost, 0.30 + 2.50)
        self.assertEqual(source, "openrouter")

    def test_a_model_present_but_unpriced_still_reports_no_cost(self):
        CatalogueEntry.objects.create(provider="gemini", model_id="silent")
        cost, source = usage.cost_of(Usage(10, 10, 20), "gemini", "silent")
        self.assertIsNone(cost)


class LedgerTests(TestCase):

    def test_an_unpriced_call_is_counted_separately_from_a_free_one(self):
        ledger = Ledger()
        ledger.add(agent="writer", usage=Usage(10, 10, 20), cost=None)
        self.assertEqual(ledger.spend_usd, 0.0)
        self.assertEqual(ledger.unpriced_calls, 1)
        # The distinction that matters: the total is not the whole bill.
        self.assertFalse(ledger.complete)

    def test_a_call_that_reported_no_tokens_is_counted_separately_again(self):
        ledger = Ledger()
        ledger.add(agent="writer", usage=None, cost=None)
        self.assertEqual(ledger.unmeasured_calls, 1)
        self.assertEqual(ledger.tokens, 0)
        self.assertFalse(ledger.complete)

    def test_a_fully_priced_ledger_says_so(self):
        ledger = Ledger()
        ledger.add(agent="writer", usage=Usage(10, 10, 20), cost=0.5)
        self.assertTrue(ledger.complete)
        self.assertEqual(ledger.spend_usd, 0.5)

    def test_the_summary_admits_what_it_does_not_know(self):
        ledger = Ledger()
        ledger.add(agent="a", usage=Usage(10, 10, 20), cost=0.25)
        ledger.add(agent="b", usage=Usage(10, 10, 20), cost=None)
        summary = ledger.summary()
        self.assertIn("$0.2500", summary)
        self.assertIn("unpriced", summary)

    def test_it_attributes_spend_per_agent(self):
        ledger = Ledger()
        ledger.add(agent="writer", usage=Usage(10, 10, 20), cost=0.25)
        ledger.add(agent="writer", usage=Usage(10, 10, 20), cost=0.25)
        ledger.add(agent="verifier", usage=Usage(5, 5, 10), cost=0.10)
        self.assertEqual(ledger.by_agent["writer"]["calls"], 2)
        self.assertAlmostEqual(ledger.by_agent["writer"]["spend_usd"], 0.5)
        self.assertAlmostEqual(ledger.by_agent["verifier"]["spend_usd"], 0.10)


class AccountingScopeTests(TestCase):

    def test_calls_land_in_the_active_ledger(self):
        with usage.accounting(label="run") as ledger:
            usage.record(_Response(LIVE_SHAPE), provider="gemini",
                         model="unpriced-model", agent="writer")
        self.assertEqual(ledger.calls, 1)
        self.assertEqual(ledger.prompt_tokens, 13)

    def test_there_is_no_ledger_outside_a_block(self):
        self.assertIsNone(usage.active_ledger())

    def test_a_nested_block_restores_the_outer_one(self):
        with usage.accounting(label="outer") as outer:
            with usage.accounting(label="inner") as inner:
                self.assertIs(usage.active_ledger(), inner)
            self.assertIs(usage.active_ledger(), outer)
        self.assertIsNone(usage.active_ledger())

    def test_the_ledger_supplies_the_label_and_run_a_call_did_not_name(self):
        with usage.accounting(label="nightly", run_id=42):
            row = usage.record(_Response(LIVE_SHAPE), provider="gemini",
                               model="m", agent="writer")
        self.assertEqual(row.label, "nightly")
        self.assertEqual(row.run_id, 42)


class RecordTests(TestCase):

    def test_a_measured_call_becomes_a_row(self):
        CatalogueEntry.objects.create(
            provider="gemini", model_id="models/gemini-2.5-flash",
            input_price_per_mtok=Decimal("0.30"),
            output_price_per_mtok=Decimal("2.50"),
            price_source=CatalogueEntry.OPENROUTER,
        )
        row = usage.record(
            _Response(LIVE_SHAPE, {"model_name": "gemini-2.5-flash"}),
            provider="gemini", model="gemini-2.5-flash", agent="writer",
            role="creative",
        )
        self.assertEqual(row.prompt_tokens, 13)
        self.assertEqual(row.reasoning_tokens, 115)
        self.assertIsNotNone(row.cost_usd)
        self.assertEqual(row.price_source, "openrouter")

    def test_an_unmeasured_call_writes_no_row(self):
        # A row of zeros would read as a free call in every total it appears in.
        self.assertIsNone(usage.record(_Response(None), provider="gemini", model="m"))
        self.assertEqual(ModelInvocation.objects.count(), 0)

    def test_an_unpriced_call_is_recorded_with_a_null_cost(self):
        row = usage.record(_Response(LIVE_SHAPE), provider="gemini",
                           model="nothing-knows-this-price")
        self.assertIsNotNone(row)
        self.assertIsNone(row.cost_usd)

    def test_accounting_never_raises_into_the_caller(self):
        """A metering failure must not be attributed to the agent.

        If it were, the obvious fix would be to remove the metering.
        """
        with patch("ai_workflows.harness.usage.usage_of",
                   side_effect=RuntimeError("bookkeeping exploded")):
            self.assertIsNone(
                usage.record(_Response(LIVE_SHAPE), provider="gemini", model="m")
            )

    def test_a_database_failure_is_swallowed_too(self):
        with patch("ai_workflows.models.ModelInvocation.objects.create",
                   side_effect=RuntimeError("the table is gone")):
            self.assertIsNone(
                usage.record(_Response(LIVE_SHAPE), provider="gemini", model="m")
            )


class TotalsTests(TestCase):

    def setUp(self):
        for cost, agent in ((Decimal("0.10"), "writer"),
                            (Decimal("0.20"), "writer"),
                            (None, "verifier")):
            ModelInvocation.objects.create(
                provider="gemini", model_id="m", agent=agent,
                prompt_tokens=10, completion_tokens=10, total_tokens=20,
                cost_usd=cost, label="nightly",
            )

    def test_it_sums_what_is_priced_and_counts_what_is_not(self):
        ledger = usage.totals(label="nightly")
        self.assertEqual(ledger.calls, 3)
        self.assertAlmostEqual(ledger.spend_usd, 0.30)
        self.assertEqual(ledger.unpriced_calls, 1)
        self.assertFalse(ledger.complete)

    def test_it_filters_by_agent(self):
        self.assertEqual(usage.totals(agent="writer").calls, 2)
