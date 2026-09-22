"""Two small defects that cost money rather than correctness.

The assistant's system prompt carried a second-granularity clock, and provider
prompt caching matches on an exact prefix -- so the highest-volume path in the
system produced a different prefix on every request and could never get a cache
hit. Rounding it to the hour was the first fix and left a comment saying the
rest belonged with the harness work; step 7 finished it by moving the clock to
a tool, so these tests now assert the stronger property.

And `langsmith_tracing` was declared as a `str`, so the string "false" was
truthy and the setting meant to control tracing could not.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import TestCase

from ai_workflows.harness.tools import SUITES
from ai_workflows.service import RESPONSE_FORMAT, ASSISTANT_PERSONA, system_prompt
from ai_workflows.tools import current_time
from brandtechsolution.config import AppSettings


class SystemPromptStabilityTests(TestCase):
    """The prompt is now static, which is as stable as a prefix can be."""

    BASE = datetime(2026, 9, 21, 10, 0, 0, tzinfo=timezone.utc)

    def test_the_prompt_does_not_vary_with_the_clock_at_all(self):
        """The original regression, in its strongest form.

        Renders seconds apart used to differ, then -- after the clock was
        rounded -- renders an hour apart still did. Time is advanced by a year
        here and the prompt has to come back byte for byte identical, because
        nothing in it is derived from the moment any more.
        """
        renders = {
            _at(self.BASE),
            _at(self.BASE + timedelta(seconds=47)),
            _at(self.BASE + timedelta(hours=1)),
            _at(self.BASE + timedelta(days=365)),
        }
        self.assertEqual(len(renders), 1)

    def test_no_clock_survives_anywhere_in_the_prompt(self):
        rendered = system_prompt()
        self.assertNotIn("Today's date", rendered)
        self.assertNotIn("Current time", rendered)
        # A date or a time of day, in any of the shapes the old prompt used.
        self.assertIsNone(_looks_like_a_timestamp(rendered),
                          f"a timestamp reached the prompt: {_looks_like_a_timestamp(rendered)}")

    def test_no_placeholder_is_left_unsubstituted(self):
        rendered = system_prompt()
        self.assertNotIn("$", rendered)

    def test_the_assistant_has_not_stopped_knowing_the_time(self):
        """Stability must not be bought by making the assistant time-blind.

        This is the guarantee the old `test_it_does_change_when_the_hour_does`
        was protecting. It has moved from the prompt to the tool, so it is
        asserted against the tool.
        """
        self.assertIn("current_time", SUITES["assistant"])

        answer = current_time.invoke({})
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertIn(today, answer)

    def test_the_clock_tool_reports_both_zones(self):
        answer = current_time.invoke({})
        self.assertIn("EAT", answer)
        self.assertIn("UTC", answer)

    def test_the_prompt_still_carries_the_persona_and_the_contract(self):
        """Static is not the same as empty."""
        rendered = system_prompt()
        self.assertIn("Teklora Solutions assistant", rendered)
        self.assertIn("METADATA", rendered)
        self.assertIn(RESPONSE_FORMAT, rendered)


def _at(moment):
    """Render the system prompt as if `moment` were now."""
    real = datetime

    class FrozenDatetime(real):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment

    # Patched in both places a clock could still be read from: the service
    # module, and the tools module the clock moved into. If either one crept
    # back into the prompt, this would catch it.
    with patch("ai_workflows.tools.datetime", FrozenDatetime, create=True):
        return system_prompt()


def _looks_like_a_timestamp(text):
    """Return the first YYYY-MM-DD or HH:MM found, or None."""
    import re

    match = re.search(r"\d{4}-\d{2}-\d{2}|\b\d{1,2}:\d{2}\b", text)
    return match.group(0) if match else None


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
