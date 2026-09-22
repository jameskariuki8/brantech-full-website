"""Telling a limit that clears from one that does not.

Written after a live eval run failed four cases on a *per-minute* rate limit.
The failover worked exactly as designed -- it decided the provider could not
answer and moved on -- and that was the wrong answer: the provider had said
it would answer in 52 seconds.
"""
from unittest.mock import Mock

from django.test import TestCase

from ai_workflows.harness.retrying import (
    BATCH,
    DEFAULT_PAUSE,
    INTERACTIVE,
    NEVER,
    RetryPolicy,
    call_with_retries,
    retry_after,
)

PER_MINUTE = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded "
    "your current quota... Please retry in 52.108267319s.', 'details': "
    "[{'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', "
    "'quotaValue': '5'}], 'retryDelay': '52s'}}"
)

PER_DAY = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded "
    "your current quota... Please retry in 32.06295192s.', 'details': "
    "[{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', "
    "'quotaValue': '20'}], 'retryDelay': '32s'}}"
)

OVERLOADED = (
    "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is "
    "currently experiencing high demand.', 'status': 'UNAVAILABLE'}}"
)


class ClassificationTests(TestCase):
    """Which refusals are worth waiting out."""

    def test_a_per_minute_limit_is_waited_out(self):
        self.assertEqual(retry_after(RuntimeError(PER_MINUTE)), 52.0)

    def test_a_daily_quota_is_not(self):
        """It carries a ~30s retryDelay too, and honouring it means sleeping
        half a minute to be refused again."""
        self.assertIsNone(retry_after(RuntimeError(PER_DAY)))

    def test_an_overloaded_model_is_waited_out_briefly(self):
        delay = retry_after(RuntimeError(OVERLOADED))
        self.assertIsNotNone(delay)
        self.assertLessEqual(delay, 10)

    def test_a_rate_limit_with_no_stated_delay_gets_a_default(self):
        self.assertEqual(
            retry_after(RuntimeError("429 rate limit exceeded")), DEFAULT_PAUSE,
        )

    def test_the_harness_own_errors_are_never_mistaken_for_a_rate_limit(self):
        """`ModelUnavailable` contains the word "unavailable".

        A case-insensitive match on it turned every raise in the harness into
        a five-second wait, and the test suite went from ninety seconds to ten
        minutes before anyone noticed what it was doing.
        """
        from ai_workflows.harness.errors import MemoryUnavailable, ModelUnavailable

        for exc in (
            ModelUnavailable("no provider is usable", provider="gemini"),
            MemoryUnavailable("memory unavailable: no space"),
            RuntimeError("asked for an unavailable tool 'run_sql'"),
            RuntimeError("the gathering step failed"),
        ):
            with self.subTest(error=type(exc).__name__):
                self.assertIsNone(retry_after(exc))

    def test_an_ordinary_failure_is_not_retried(self):
        """A revoked key does not improve with patience."""
        self.assertIsNone(retry_after(RuntimeError("401 API key not valid")))
        self.assertIsNone(retry_after(ValueError("malformed request")))


class WaitingTests(TestCase):
    """What `call_with_retries` actually does with that verdict."""

    def setUp(self):
        self.slept = []

    def _sleep(self, seconds):
        self.slept.append(seconds)

    def test_it_waits_the_stated_delay_and_succeeds(self):
        call = Mock(side_effect=[RuntimeError(PER_MINUTE), "an answer"])

        result = call_with_retries(call, policy=BATCH, sleep=self._sleep)

        self.assertEqual(result, "an answer")
        self.assertEqual(self.slept, [52.0])

    def test_it_gives_up_after_the_policy_is_spent(self):
        call = Mock(side_effect=RuntimeError(PER_MINUTE))
        policy = RetryPolicy(attempts=2, max_wait=65)

        with self.assertRaises(RuntimeError):
            call_with_retries(call, policy=policy, sleep=self._sleep)

        self.assertEqual(len(self.slept), 2)
        self.assertEqual(call.call_count, 3)

    def test_the_provider_error_survives_the_retries(self):
        """The failover downstream needs the real reason, not a wrapper."""
        call = Mock(side_effect=RuntimeError(PER_MINUTE))

        with self.assertRaises(RuntimeError) as caught:
            call_with_retries(call, policy=RetryPolicy(1, 65), sleep=self._sleep)

        self.assertIn("RESOURCE_EXHAUSTED", str(caught.exception))

    def test_a_wait_longer_than_the_caller_allows_is_not_taken(self):
        """A visitor watching a chat box will not wait 52 seconds."""
        call = Mock(side_effect=[RuntimeError(PER_MINUTE), "an answer"])

        with self.assertRaises(RuntimeError):
            call_with_retries(call, policy=INTERACTIVE, sleep=self._sleep)

        self.assertEqual(self.slept, [])

    def test_a_daily_quota_is_handed_straight_to_the_failover(self):
        call = Mock(side_effect=RuntimeError(PER_DAY))

        with self.assertRaises(RuntimeError):
            call_with_retries(call, policy=BATCH, sleep=self._sleep)

        self.assertEqual(self.slept, [])
        self.assertEqual(call.call_count, 1)

    def test_a_policy_that_never_waits_calls_once(self):
        call = Mock(side_effect=RuntimeError(PER_MINUTE))

        with self.assertRaises(RuntimeError):
            call_with_retries(call, policy=NEVER, sleep=self._sleep)

        self.assertEqual(call.call_count, 1)

    def test_a_success_never_sleeps(self):
        self.assertEqual(
            call_with_retries(Mock(return_value="fine"), sleep=self._sleep), "fine",
        )
        self.assertEqual(self.slept, [])


class GatherIntegrationTests(TestCase):
    """The loop that lost four eval cases to a limit that had already lifted."""

    def test_the_gathering_loop_waits_before_it_fails_over(self):
        from unittest.mock import patch

        from ai_workflows.harness.gather import gather
        from ai_workflows.harness.llm import Provider

        first = Mock()
        first.invoke = Mock(side_effect=[
            RuntimeError(PER_MINUTE),
            _turn("I checked, and it holds up."),
        ])
        second = Mock()
        second.invoke = Mock(side_effect=AssertionError("should not be reached"))

        def candidates(*args, **kwargs):
            yield Provider.GEMINI, first
            yield Provider.OPENROUTER, second

        slept = []
        with patch("ai_workflows.harness.gather.iter_models", new=candidates), \
                patch("ai_workflows.harness.retrying.time.sleep", new=slept.append):
            evidence = gather(None, "check this", [_FakeTool()], agent="test")

        self.assertIn("holds up", evidence)
        self.assertEqual(slept, [52.0])
        second.invoke.assert_not_called()


class _FakeTool:
    name = "fetch_url"

    def invoke(self, args):
        return "a result"


def _turn(content):
    message = Mock()
    message.content = content
    message.tool_calls = []
    return message
