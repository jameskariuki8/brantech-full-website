"""Two small defects that cost money rather than correctness.

The assistant's system prompt carried a second-granularity clock, and provider
prompt caching matches on an exact prefix -- so the highest-volume path in the
system produced a different prefix on every request and could never get a cache
hit.

And `langsmith_tracing` was declared as a `str`, so the string "false" was
truthy and the setting meant to control tracing could not.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import TestCase

from ai_workflows.service import SYSTEM_PROMPT_TEMPLATE, _render_system_prompt
from brandtechsolution.config import AppSettings


def _at(moment):
    """Render the system prompt as if `moment` were now."""
    real = datetime

    class FrozenDatetime(real):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment

    with patch("ai_workflows.service.datetime", FrozenDatetime):
        return _render_system_prompt()


class SystemPromptStabilityTests(TestCase):
    BASE = datetime(2026, 9, 21, 10, 0, 0, tzinfo=timezone.utc)

    def test_the_prompt_is_identical_across_requests_seconds_apart(self):
        """The regression. Two calls a few seconds apart must match byte for byte."""
        first = _at(self.BASE)
        second = _at(self.BASE + timedelta(seconds=47))
        self.assertEqual(first, second)

    def test_it_is_still_identical_across_most_of_an_hour(self):
        first = _at(self.BASE)
        later = _at(self.BASE + timedelta(minutes=59))
        self.assertEqual(first, later)

    def test_it_does_change_when_the_hour_does(self):
        """Stability must not mean the assistant stops knowing the time at all."""
        first = _at(self.BASE)
        next_hour = _at(self.BASE + timedelta(hours=1))
        self.assertNotEqual(first, next_hour)

    def test_no_seconds_component_survives_in_the_rendered_prompt(self):
        rendered = _at(self.BASE.replace(minute=37, second=42))
        self.assertNotIn(":37:42", rendered)
        self.assertNotIn(":42 ", rendered)

    def test_the_date_and_time_still_reach_the_prompt(self):
        rendered = _at(self.BASE)
        self.assertIn("2026-09-21", rendered)
        self.assertIn("13:00", rendered)  # 10:00 UTC at the +3 EAT offset

    def test_no_placeholder_is_left_unsubstituted(self):
        rendered = _at(self.BASE)
        self.assertNotIn("$today_date", rendered)
        self.assertNotIn("$nairobi_time", rendered)
        # The template does declare them, so the test above means something.
        self.assertIn("$nairobi_time", SYSTEM_PROMPT_TEMPLATE.template)


class TracingSettingTests(TestCase):
    """`langsmith_tracing` has to be a real boolean.

    As `str = "true"` it could not be turned off: both readers in
    ai_workflows/service.py test it for truthiness, and the string "false" is
    truthy, so LANGSMITH_TRACING=false still resolved to enabled.
    """

    def _tracing(self, raw):
        return AppSettings(langsmith_tracing=raw).langsmith_tracing

    def test_the_default_is_on(self):
        """Unchanged behaviour: tracing stays enabled unless asked otherwise."""
        self.assertIs(AppSettings().langsmith_tracing, True)

    def test_false_spellings_disable_it(self):
        for raw in ("false", "False", "0", "no", "off"):
            with self.subTest(raw=raw):
                self.assertIs(self._tracing(raw), False)

    def test_true_spellings_enable_it(self):
        for raw in ("true", "True", "1", "yes", "on"):
            with self.subTest(raw=raw):
                self.assertIs(self._tracing(raw), True)

    def test_it_is_a_bool_not_a_string(self):
        """The whole bug in one assertion: "false" must not be truthy."""
        self.assertNotIsInstance(self._tracing("false"), str)
        self.assertFalse(self._tracing("false"))
