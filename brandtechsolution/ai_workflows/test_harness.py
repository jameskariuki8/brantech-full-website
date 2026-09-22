"""Step 1 of the harness: the foundations, with no callers yet.

Nothing in here touches a provider. Every model is a stub, because the point
of these tests is the harness's own behaviour -- what it does with what a model
said -- and a live call would make each run measure a different question.
"""
from unittest.mock import patch

from django.test import TestCase
from langchain_core.messages import SystemMessage
from pydantic import ValidationError

from ai_workflows.harness.base import (
    Agent,
    AgentRegistry,
    AgentRequest,
    AgentResult,
)
from ai_workflows.harness.context import (
    ContextAssembler,
    Fragment,
    approximate_tokens,
    truncate_tool_result,
)
from ai_workflows.harness.contract import (
    AgentOutput,
    OutputStatus,
    ask,
    parse_json,
    strip_fence,
)
from ai_workflows.harness.errors import AgentOutputInvalid, ModelUnavailable
from ai_workflows.harness.llm import ModelRole, ROLE_TEMPERATURE, get_model
from ai_workflows.harness.persona import DEFAULT_VOICE, Persona
from ai_workflows.harness.steps import StepCache, step_key
from ai_workflows.models import StepResult


class Draft(AgentOutput):
    title: str = ""
    body: str = ""


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeModel:
    """Returns queued responses; records what it was sent."""

    def __init__(self, *responses, structured=False):
        self._responses = list(responses)
        self.calls = []
        self._structured = structured

    def invoke(self, messages, *a, **kw):
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("FakeModel ran out of queued responses")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt if not isinstance(nxt, str) else FakeResponse(nxt)

    def with_structured_output(self, schema):
        if not self._structured:
            raise NotImplementedError("no native structured output")
        return self


# ============================================================
# Personas
# ============================================================

class PersonaTests(TestCase):
    def test_the_rendered_prompt_carries_role_voice_and_directives(self):
        persona = Persona(
            name="verifier", role="the Lead Fact Verification Editor at Teklora",
            directives=("Check every statistic against its source.",),
            constraints=("Never assert a figure the sources do not contain.",),
        )
        rendered = persona.render()

        self.assertIn("Lead Fact Verification Editor", rendered)
        self.assertIn(DEFAULT_VOICE, rendered)
        self.assertIn("Check every statistic", rendered)
        self.assertIn("Never assert a figure", rendered)

    def test_rendering_is_stable_across_calls(self):
        """It is the front of the cached prefix; it must not vary."""
        persona = Persona(name="a", role="an agent")
        self.assertEqual(persona.render(), persona.render())
        self.assertEqual(persona.fingerprint(), persona.fingerprint())

    def test_changing_a_directive_changes_the_fingerprint(self):
        """Otherwise an edited prompt would be served from a stale step cache."""
        one = Persona(name="a", role="an agent", directives=("be brief",))
        two = Persona(name="a", role="an agent", directives=("be thorough",))
        self.assertNotEqual(one.fingerprint(), two.fingerprint())

    def test_the_voice_can_be_replaced_without_touching_the_persona(self):
        persona = Persona(name="a", role="an agent")
        revoiced = persona.with_voice("Terse and factual.")
        self.assertIn("Terse and factual.", revoiced.render())
        self.assertEqual(persona.voice, DEFAULT_VOICE)  # original untouched

    def test_mutable_defaults_cannot_leak_between_personas(self):
        persona = Persona(name="a", role="an agent", directives=["one"])
        self.assertIsInstance(persona.directives, tuple)


# ============================================================
# Model access
# ============================================================

class ModelAccessTests(TestCase):
    def test_every_role_has_a_temperature(self):
        for role in ModelRole:
            self.assertIn(role, ROLE_TEMPERATURE)

    def test_the_roles_match_what_the_agents_use_today(self):
        """Adopting the harness must not also be a silent behaviour change."""
        self.assertEqual(ROLE_TEMPERATURE[ModelRole.PRECISE], 0.1)   # verifier
        self.assertEqual(ROLE_TEMPERATURE[ModelRole.CREATIVE], 0.4)  # writer, social

    # Patched at the adapter, which is where a credential is defined. It used
    # to be enough to blank `llm.config`, but the multi-provider work moved
    # credential lookup into the adapters so there would be exactly one answer
    # to "where does this provider's key come from" -- and a test that blanks
    # one of several module-level `config` references would pass or fail on
    # which import it happened to name.
    NO_KEY = "ai_workflows.harness.providers.GeminiAdapter.credential"

    def test_a_missing_key_raises_rather_than_returning_none(self):
        """The whole reason this function exists.

        `self.model = None` is what let a rotated key become published
        fabrications instead of a failed run.
        """
        with patch(self.NO_KEY, return_value=""):
            with self.assertRaises(ModelUnavailable):
                get_model(ModelRole.PRECISE, agent="verifier")

    def test_the_error_names_the_agent_that_wanted_the_model(self):
        with patch(self.NO_KEY, return_value=""):
            with self.assertRaises(ModelUnavailable) as caught:
                get_model(ModelRole.PRECISE, agent="verifier")
        self.assertEqual(caught.exception.agent, "verifier")
        self.assertIn("verifier", str(caught.exception))


# ============================================================
# Context assembly
# ============================================================

class ContextTests(TestCase):
    def setUp(self):
        self.persona = Persona(name="a", role="an agent")

    def test_the_persona_leads_and_volatile_content_trails(self):
        """Caching matches an exact prefix; anything per-request must come last."""
        assembled = ContextAssembler(max_tokens=1000).assemble(
            persona=self.persona,
            fragments=[Fragment(content="history", order=1)],
            volatile=["Current time: 13:47:02"],
        )
        contents = [m.content for m in assembled.messages]

        self.assertIn("an agent", contents[0])
        self.assertIn("13:47:02", contents[-1])

    def test_low_salience_is_dropped_before_high_salience(self):
        """A recency cut would have kept the chatter and dropped the fact."""
        assembler = ContextAssembler(max_tokens=approximate_tokens("x" * 400))
        assembled = assembler.assemble(
            fragments=[
                Fragment(content="x" * 200, salience=0.1, order=1, kind="chatter"),
                Fragment(content="y" * 200, salience=0.9, order=2, kind="fact"),
                Fragment(content="z" * 200, salience=0.2, order=3, kind="chatter"),
            ],
        )
        kept = " ".join(m.content for m in assembled.messages)
        self.assertIn("y" * 200, kept)
        self.assertTrue(assembled.dropped)

    def test_surviving_fragments_are_returned_in_order(self):
        """Ranked for eviction, but the model reads a conversation."""
        assembled = ContextAssembler(max_tokens=10_000).assemble(
            fragments=[
                Fragment(content="first", salience=0.1, order=1),
                Fragment(content="second", salience=0.9, order=2),
                Fragment(content="third", salience=0.5, order=3),
            ],
        )
        contents = [m.content for m in assembled.messages]
        self.assertEqual(contents, ["first", "second", "third"])

    def test_pinned_fragments_survive_an_impossible_budget(self):
        assembled = ContextAssembler(max_tokens=1).assemble(
            fragments=[
                Fragment(content="x" * 4000, salience=0.0, order=1, pinned=True),
                Fragment(content="y" * 4000, salience=0.9, order=2),
            ],
        )
        kept = " ".join(m.content for m in assembled.messages)
        self.assertIn("x" * 4000, kept)
        self.assertEqual(assembled.dropped_count, 1)

    def test_a_budget_of_zero_is_refused(self):
        with self.assertRaises(ValueError):
            ContextAssembler(max_tokens=0)

    def test_a_long_tool_result_is_capped_and_says_so(self):
        """A silently truncated document gets reasoned about as if complete."""
        capped = truncate_tool_result("x" * 10_000, limit=100)
        self.assertLess(len(capped), 400)
        self.assertIn("truncated", capped)

    def test_a_short_tool_result_is_untouched(self):
        self.assertEqual(truncate_tool_result("brief", limit=100), "brief")


# ============================================================
# The prompt contract
# ============================================================

class FenceTests(TestCase):
    def test_a_fenced_block_is_unwrapped(self):
        self.assertEqual(strip_fence('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(strip_fence('```\n{"a": 1}\n```'), '{"a": 1}')

    def test_bare_json_is_left_alone(self):
        self.assertEqual(strip_fence('{"a": 1}'), '{"a": 1}')

    def test_empty_input_is_not_an_error_here(self):
        self.assertEqual(strip_fence(""), "")


class ParseTests(TestCase):
    def test_valid_json_validates_into_the_schema(self):
        draft = parse_json('{"title": "T", "body": "B"}', Draft)
        self.assertEqual(draft.title, "T")
        self.assertIs(draft.status, OutputStatus.OK)

    def test_invalid_json_raises_with_the_offending_text(self):
        with self.assertRaises(AgentOutputInvalid) as caught:
            parse_json("{not json", Draft)
        self.assertEqual(caught.exception.raw, "{not json")

    def test_a_json_array_is_refused(self):
        with self.assertRaises(AgentOutputInvalid):
            parse_json("[1, 2]", Draft)

    def test_a_schema_violation_is_refused(self):
        with self.assertRaises(AgentOutputInvalid):
            parse_json('{"confidence": 4.2}', Draft)  # ge=0 le=1


class AbstentionTests(TestCase):
    def test_a_default_output_is_usable(self):
        self.assertTrue(Draft().usable)
        self.assertFalse(Draft().abstained)

    def test_insufficient_evidence_is_an_abstention_not_a_result(self):
        draft = Draft(status=OutputStatus.INSUFFICIENT_EVIDENCE,
                      notes="no sources supported the claim")
        self.assertTrue(draft.abstained)
        self.assertFalse(draft.usable)

    def test_abstention_survives_the_json_round_trip(self):
        draft = parse_json('{"status": "insufficient_evidence"}', Draft)
        self.assertTrue(draft.abstained)

    def test_confidence_is_bounded(self):
        with self.assertRaises(ValidationError):
            Draft(confidence=1.5)


class AskTests(TestCase):
    PERSONA = Persona(name="writer", role="a writer")

    def test_a_valid_response_is_returned_validated(self):
        model = FakeModel('{"title": "T", "body": "B"}')
        draft = ask(self.PERSONA, "write", Draft, model=model)
        self.assertEqual(draft.title, "T")

    def test_an_invalid_response_is_retried_with_the_error(self):
        """The model is told what was wrong, not merely re-rolled."""
        model = FakeModel("{broken", '{"title": "second try"}')
        draft = ask(self.PERSONA, "write", Draft, model=model, retries=1)

        self.assertEqual(draft.title, "second try")
        self.assertEqual(len(model.calls), 2)
        correction = model.calls[1][-1].content
        self.assertIn("rejected", correction)

    def test_it_raises_rather_than_returning_a_canned_object(self):
        """The lesson of the fallback drafts: a plausible fake is worse than a failure."""
        model = FakeModel("{broken", "{still broken")
        with self.assertRaises(AgentOutputInvalid):
            ask(self.PERSONA, "write", Draft, model=model, retries=1, agent="writer")

    def test_a_model_outage_propagates_untouched(self):
        model = FakeModel(ModelUnavailable("provider down"))
        with self.assertRaises(ModelUnavailable):
            ask(self.PERSONA, "write", Draft, model=model)

    def test_the_persona_is_sent_as_the_first_message(self):
        model = FakeModel('{"title": "T"}')
        ask(self.PERSONA, "write", Draft, model=model)
        first = model.calls[0][0]
        self.assertIsInstance(first, SystemMessage)
        self.assertIn("a writer", first.content)

    def test_native_structured_output_is_used_when_available(self):
        model = FakeModel(Draft(title="native"), structured=True)
        draft = ask(self.PERSONA, "write", Draft, model=model)
        self.assertEqual(draft.title, "native")


# ============================================================
# Step cache
# ============================================================

class StepKeyTests(TestCase):
    def test_key_order_does_not_matter(self):
        """Dicts preserve insertion order, so without sorting every lookup misses."""
        self.assertEqual(
            step_key("s", {"a": 1, "b": 2}),
            step_key("s", {"b": 2, "a": 1}),
        )

    def test_different_inputs_key_differently(self):
        self.assertNotEqual(step_key("s", {"a": 1}), step_key("s", {"a": 2}))

    def test_a_changed_fingerprint_changes_the_key(self):
        """Editing a persona must not be served from the old cache."""
        self.assertNotEqual(
            step_key("s", {"a": 1}, fingerprint="v1"),
            step_key("s", {"a": 1}, fingerprint="v2"),
        )


class StepCacheTests(TestCase):
    def test_a_repeated_step_is_not_recomputed(self):
        calls = []

        def produce():
            calls.append(1)
            return {"n": len(calls)}

        cache = StepCache(agent="writer")
        first = cache.run("draft", {"topic": "agents"}, produce)
        second = cache.run("draft", {"topic": "agents"}, produce)

        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(StepResult.objects.count(), 1)

    def test_changed_inputs_recompute(self):
        cache = StepCache()
        cache.run("draft", {"topic": "a"}, lambda: {"v": 1})
        cache.run("draft", {"topic": "b"}, lambda: {"v": 2})
        self.assertEqual(StepResult.objects.count(), 2)

    def test_a_changed_fingerprint_recomputes(self):
        cache = StepCache()
        cache.run("draft", {"t": "a"}, lambda: {"v": 1}, fingerprint="v1")
        cache.run("draft", {"t": "a"}, lambda: {"v": 2}, fingerprint="v2")
        self.assertEqual(StepResult.objects.count(), 2)

    def test_a_failure_is_not_cached(self):
        """A transient outage must not become permanent for those inputs."""
        cache = StepCache()

        def boom():
            raise RuntimeError("provider down")

        with self.assertRaises(RuntimeError):
            cache.run("draft", {"t": "a"}, boom)

        self.assertEqual(StepResult.objects.count(), 0)
        self.assertEqual(cache.run("draft", {"t": "a"}, lambda: {"v": 1}), {"v": 1})

    def test_disabling_the_cache_always_recomputes(self):
        """An eval measuring a cached answer is measuring the cache."""
        calls = []
        cache = StepCache(enabled=False)
        for _ in range(3):
            cache.run("draft", {"t": "a"}, lambda: calls.append(1))
        self.assertEqual(len(calls), 3)
        self.assertEqual(StepResult.objects.count(), 0)

    def test_invalidate_clears_one_step(self):
        cache = StepCache()
        cache.run("draft", {"t": "a"}, lambda: {"v": 1})
        cache.run("verify", {"t": "a"}, lambda: {"v": 2})

        cache.invalidate("draft")
        self.assertEqual(StepResult.objects.filter(step="draft").count(), 0)
        self.assertEqual(StepResult.objects.filter(step="verify").count(), 1)


# ============================================================
# The agent contract
# ============================================================

class Demo(Agent):
    name = "demo"
    persona = Persona(name="demo", role="a demo agent")

    def run(self, request):
        return AgentResult(agent=self.name, output=request.payload)


class AgentContractTests(TestCase):
    def test_an_agent_runs_through_the_contract(self):
        result = Demo().run(AgentRequest(payload={"x": 1}))
        self.assertEqual(result.output, {"x": 1})
        self.assertTrue(result.usable)

    def test_an_abstaining_result_is_not_usable(self):
        result = AgentResult(agent="demo", abstained=True, notes="no evidence")
        self.assertFalse(result.usable)

    def test_the_fingerprint_follows_the_persona(self):
        agent, other = Demo(), Demo()
        other.persona = Demo.persona.with_voice("Terse.")
        self.assertNotEqual(agent.fingerprint(), other.fingerprint())

    def test_an_agent_cannot_be_instantiated_without_run(self):
        class Incomplete(Agent):
            name = "incomplete"

        with self.assertRaises(TypeError):
            Incomplete()


class RegistryTests(TestCase):
    def test_an_agent_resolves_by_name(self):
        registry = AgentRegistry()
        registry.register(Demo())
        self.assertEqual(registry.get("demo").name, "demo")
        self.assertIn("demo", registry)

    def test_a_duplicate_name_is_refused(self):
        registry = AgentRegistry()
        registry.register(Demo())
        with self.assertRaises(ValueError):
            registry.register(Demo())

    def test_an_unknown_name_lists_what_is_registered(self):
        registry = AgentRegistry()
        registry.register(Demo())
        with self.assertRaises(KeyError) as caught:
            registry.get("nope")
        self.assertIn("demo", str(caught.exception))


# ============================================================
# The structured-output path, and what it reports
# ============================================================


class RawAwareModel:
    """A model whose structured binding returns the `include_raw` shape.

    `FakeModel` above deliberately does not take the flag, which exercises the
    other branch: a binding that cannot report usage still has to work.
    """

    def __init__(self, *results, usage_metadata=None):
        self._results = list(results)
        self.include_raw = None
        self.model = "fake-model"
        self._usage = usage_metadata

    def invoke(self, messages, *a, **kw):
        if not self._results:
            raise AssertionError("RawAwareModel ran out of queued results")
        return self._results.pop(0)

    def with_structured_output(self, schema, include_raw=False):
        self.include_raw = include_raw
        return self

    def raw(self, content="{}"):
        message = FakeResponse(content)
        message.usage_metadata = self._usage
        message.response_metadata = {"model_name": "fake-model"}
        return message


class StructuredOutputTests(TestCase):

    def test_the_raw_message_is_asked_for_when_the_binding_supports_it(self):
        """Without it, the most-used call path is the one that reports no usage
        -- `with_structured_output` returns the parsed object and drops the
        message carrying the token counts."""
        from ai_workflows.harness.contract import _structured

        model = RawAwareModel()
        _structured(model, Draft)
        self.assertTrue(model.include_raw)

    def test_a_binding_that_cannot_take_the_flag_still_works(self):
        from ai_workflows.harness.contract import _structured

        model = FakeModel(structured=True)
        self.assertIsNotNone(_structured(model, Draft))

    def test_a_schema_violation_is_a_shape_failure_not_an_outage(self):
        """It used to be neither: the binding raised, the broad catch relabelled
        it `ModelUnavailable`, and an alert sent somebody to look for an outage
        over a response that had arrived perfectly well."""
        from ai_workflows.harness.contract import _ask_one
        from ai_workflows.harness.errors import AgentOutputInvalid

        model = RawAwareModel()
        broken = {"raw": model.raw("not json"), "parsed": None,
                  "parsing_error": "title: field required"}
        model._results = [broken, broken]

        with self.assertRaises(AgentOutputInvalid):
            _ask_one(model, [], Draft, retries=1, agent="writer")

    def test_the_parsed_object_is_returned_when_there_is_one(self):
        from ai_workflows.harness.contract import _ask_one

        model = RawAwareModel()
        wanted = Draft(title="t", body="b")
        model._results = [{"raw": model.raw(), "parsed": wanted,
                           "parsing_error": None}]

        self.assertIs(_ask_one(model, [], Draft, retries=0, agent="writer"), wanted)

    def test_the_call_is_accounted_for(self):
        from ai_workflows.harness import usage
        from ai_workflows.harness.contract import _ask_one

        model = RawAwareModel(usage_metadata={
            "input_tokens": 11, "output_tokens": 22, "total_tokens": 33,
        })
        model._results = [{"raw": model.raw(), "parsed": Draft(title="t"),
                           "parsing_error": None}]

        with usage.accounting(label="t") as ledger:
            _ask_one(model, [], Draft, retries=0, agent="writer",
                     provider="gemini")

        self.assertEqual(ledger.calls, 1)
        self.assertEqual(ledger.prompt_tokens, 11)
        self.assertEqual(ledger.completion_tokens, 22)

    def test_an_unpackable_result_is_read_in_every_shape(self):
        from ai_workflows.harness.contract import _unpack

        message = FakeResponse("{}")
        self.assertEqual(
            _unpack({"raw": message, "parsed": None, "parsing_error": "x"}, Draft),
            (message, None, "x"),
        )
        wanted = Draft(title="t")
        self.assertEqual(_unpack(wanted, Draft), (None, wanted, None))
        self.assertEqual(_unpack(message, Draft), (message, None, None))
