"""Step 7: the assistant on the harness.

Three things changed that a user or an operator would notice, and each has its
own class below: the metadata block stops leaking into replies, an unreachable
model stops being a private apology, and the brand voice stops being defined
twice.
"""
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core import mail
from django.test import TestCase

from ai_workflows.harness.alerts import ALERT_CAPABILITY
from ai_workflows.harness.errors import ModelUnavailable
from ai_workflows.models import AgentHealth, AgentProfile
from ai_workflows.service import (
    ChatAssistant,
    ReplyMetadata,
    get_chatbot_response,
    split_metadata,
    system_prompt,
)


class FakeGraph:
    """Stands in for the compiled react agent."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def invoke(self, state, config=None, **kwargs):
        self.calls.append(state)
        return {"messages": [type("M", (), {"content": self.reply})()]}


def _assistant(reply="Hello.", **kwargs):
    """An assistant with its graph injected.

    Injected rather than patched at construction: since the model is resolved
    lazily -- so that reading history does not require a working provider --
    the graph is not built until first use, by which point a patch applied
    around the constructor has long since exited.
    """
    assistant = ChatAssistant(thread_id="t-1", **kwargs)
    assistant._app = FakeGraph(reply)
    return assistant


REPLY_WITH_METADATA = """Teklora builds responsive sites with Django and React.

METADATA
```json
{"sources": [{"type": "project", "id": 1, "title": "Test Project", "excerpt": "A React app."}],
 "follow_up_questions": ["Want links to the project?"]}
```"""


class MetadataTests(TestCase):
    """The block the prompt has always asked for and nothing ever read."""

    def test_the_block_is_stripped_from_what_the_user_sees(self):
        reply, _ = split_metadata(REPLY_WITH_METADATA)
        self.assertNotIn("METADATA", reply)
        self.assertNotIn("sources", reply)
        self.assertTrue(reply.endswith("Django and React."))

    def test_the_block_is_parsed_rather_than_discarded(self):
        _, metadata = split_metadata(REPLY_WITH_METADATA)
        self.assertEqual(len(metadata.sources), 1)
        self.assertEqual(metadata.sources[0].title, "Test Project")
        self.assertEqual(metadata.follow_up_questions, ["Want links to the project?"])

    def test_a_reply_without_a_block_is_untouched(self):
        reply, metadata = split_metadata("Just an answer.")
        self.assertEqual(reply, "Just an answer.")
        self.assertEqual(metadata, ReplyMetadata())

    def test_prose_mentioning_metadata_is_not_mistaken_for_a_block(self):
        """Anchored on a lone marker line, so ordinary prose is safe."""
        text = "The METADATA field in that schema is optional."
        reply, _ = split_metadata(text)
        self.assertEqual(reply, text)

    def test_an_unfenced_block_is_still_understood(self):
        reply, metadata = split_metadata(
            'An answer.\n\nMETADATA\n{"follow_up_questions": ["And then?"]}'
        )
        self.assertEqual(reply, "An answer.")
        self.assertEqual(metadata.follow_up_questions, ["And then?"])

    def test_a_malformed_block_is_removed_and_logged(self):
        """Showing somebody broken JSON is not better than showing valid JSON."""
        with self.assertLogs("ai_workflows.service", level="WARNING"):
            reply, metadata = split_metadata("An answer.\n\nMETADATA\n```json\n{oops\n```")

        self.assertEqual(reply, "An answer.")
        self.assertEqual(metadata, ReplyMetadata())

    def test_the_reply_reaching_the_caller_carries_both_halves(self):
        result = _assistant(REPLY_WITH_METADATA).send_message("hi")

        self.assertNotIn("METADATA", result["response"])
        self.assertEqual(result["suggested_questions"], ["Want links to the project?"])
        self.assertEqual(result["sources"][0]["title"], "Test Project")

    def test_suggested_questions_are_no_longer_hardcoded_empty(self):
        """They were declared on the TypedDict, asked for in the prompt,
        produced by the model, and returned as [] regardless."""
        plain = _assistant("No metadata here.").send_message("hi")
        self.assertEqual(plain["suggested_questions"], [])

        rich = _assistant(REPLY_WITH_METADATA).send_message("hi")
        self.assertNotEqual(rich["suggested_questions"], [])


class HistoryTests(TestCase):
    def test_history_does_not_replay_metadata_blocks(self):
        """Replies saved before step 7 have their JSON attached."""
        assistant = _assistant()
        checkpoint = type("C", (), {"checkpoint": {
            "channel_values": {"messages": [
                {"type": "ai", "content": REPLY_WITH_METADATA},
            ]}
        }})()

        with patch.object(assistant.checkpointer, "get_tuple", return_value=checkpoint):
            history = assistant.get_history()

        self.assertEqual(len(history), 1)
        self.assertNotIn("METADATA", history[0]["content"])


class FailureTests(TestCase):
    """An outage used to be an apology to one user and nothing else."""

    def setUp(self):
        user = User.objects.create_user("ops", email="ops@example.com", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename=ALERT_CAPABILITY))

    def test_an_unreachable_model_pages_somebody(self):
        with patch("ai_workflows.service.get_model",
                   side_effect=ModelUnavailable("no key", provider="gemini")):
            result = get_chatbot_response("hi", thread_id="t-1")

        self.assertIn("can't reach my tools", result["response"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("assistant is failing", mail.outbox[0].subject)

    def test_the_user_still_gets_a_usable_reply(self):
        """The edge is the one place errors.py allows a catch: a chat view has
        to render something."""
        with patch("ai_workflows.service.get_model",
                   side_effect=ModelUnavailable("no key")):
            result = get_chatbot_response("hi", thread_id="t-1")

        self.assertTrue(result["response"])
        self.assertEqual(result["thread_id"], "t-1")
        self.assertEqual(result["metadata"]["suggested_questions"], [])

    def test_a_failure_mid_conversation_is_recorded_too(self):
        assistant = _assistant()
        with patch.object(assistant.app, "invoke", side_effect=RuntimeError("boom")):
            result = assistant.send_message("hi")

        self.assertIn("can't reach my tools", result["response"])
        self.assertTrue(AgentHealth.objects.get(agent="assistant").is_failing)

    def test_recovery_is_announced(self):
        assistant = _assistant()
        with patch.object(assistant.app, "invoke", side_effect=RuntimeError("boom")):
            assistant.send_message("hi")
        mail.outbox.clear()

        assistant.send_message("hi again")

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("working again", mail.outbox[0].subject)


class OneBrandVoiceTests(TestCase):
    """The assistant was the codebase's second definition of the brand voice."""

    def test_the_prompt_carries_the_stored_voice(self):
        profile = AgentProfile.load()
        profile.brand_voice = "Terse, sceptical, allergic to adjectives."
        profile.save()

        self.assertIn("allergic to adjectives", _assistant()._system_prompt)

    def test_it_is_the_same_voice_the_newsroom_uses(self):
        from editorial.services.writer import AIWriterAgent

        profile = AgentProfile.load()
        profile.brand_voice = "One voice."
        profile.save()

        self.assertEqual(
            ChatAssistant.persona.with_voice(profile.brand_voice).voice,
            AIWriterAgent().voiced_persona().voice,
        )

    def test_the_declared_personas_are_still_distinct(self):
        """One voice, not one persona."""
        from editorial.services.writer import AIWriterAgent

        self.assertNotEqual(ChatAssistant.persona.role, AIWriterAgent.persona.role)


class HarnessContractTests(TestCase):
    def test_the_assistant_is_dispatchable_like_any_other_agent(self):
        from ai_workflows.harness.base import Agent, AgentRequest

        assistant = _assistant()
        self.assertIsInstance(assistant, Agent)

        result = assistant.run(AgentRequest(payload={"message": "hi"}))
        self.assertEqual(result.agent, "assistant")
        self.assertTrue(result.usable)

    def test_it_declares_its_role_and_suite(self):
        from ai_workflows.harness.llm import ModelRole

        self.assertIs(ChatAssistant.model_role, ModelRole.CONVERSATIONAL)
        self.assertEqual(ChatAssistant.tool_suite, "assistant")

    def test_the_system_prompt_is_built_once_not_per_turn(self):
        """It has no per-request content left, so re-rendering could only
        reintroduce some."""
        assistant = _assistant()
        self.assertEqual(assistant._system_prompt, system_prompt(assistant.voiced_persona()))


class NoProviderTests(TestCase):
    """History has to survive an outage the assistant itself cannot."""

    def test_history_is_readable_with_no_usable_provider(self):
        """The regression that made this lazy.

        Resolving a model in the constructor meant that during a provider
        outage a user could not read what they had already said -- the history
        endpoint returned 500, which is a worse experience than the outage.
        """
        from ai_workflows.models import Provider as ProviderRow

        ProviderRow.objects.all().delete()
        with patch("ai_workflows.harness.catalogue.can_serve", return_value=False):
            assistant = ChatAssistant(thread_id="t-outage")
            self.assertEqual(assistant.get_history(), [])

    def test_sending_a_message_during_the_outage_still_fails_loudly(self):
        """Lazy is not the same as forgiving."""
        from ai_workflows.models import Provider as ProviderRow

        ProviderRow.objects.all().delete()
        with patch("ai_workflows.harness.catalogue.can_serve", return_value=False):
            assistant = ChatAssistant(thread_id="t-outage")
            result = assistant.send_message("hi")

        self.assertIn("can't reach my tools", result["response"])

    def test_the_tools_are_still_wired_without_a_provider(self):
        """Tool resolution must not depend on a model being reachable."""
        from ai_workflows.models import Provider as ProviderRow

        ProviderRow.objects.all().delete()
        with patch("ai_workflows.harness.catalogue.can_serve", return_value=False):
            assistant = ChatAssistant(thread_id="t-outage")

        self.assertEqual(len(assistant.tools), 3)
