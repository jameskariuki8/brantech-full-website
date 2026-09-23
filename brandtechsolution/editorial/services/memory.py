"""
Module 17: Editorial Memory Agent

Stops the newsroom covering the same story twice.

On the harness since step 6. The check used to be
`title__icontains=title[:20]`, which catches a literal republish and nothing
else: "OpenAI Ships GPT-5 Agents" and "GPT-5's Agent Mode, Explained" share no
20-character prefix, so both would have been researched, written and queued.
The substring check is kept -- it is cheap, exact and catches the case it was
written for -- and a semantic check is added behind it for everything else.

`EditorialMemory` stays as the editorial-side settings row. The brand voice it
holds has moved to `AgentProfile`, which is what every agent now reads; the two
are seeded identically, and this agent is no longer the only thing consulting
it.
"""
import logging

from editorial.models import EditorialArticle, EditorialMemory

logger = logging.getLogger(__name__)

# Cosine similarity above which two topics are the same story. A judgement
# call, and named so a reader can see it is one: raise it and the newsroom
# covers near-duplicates, lower it and it declines stories because it once
# wrote about the same company. Tuned against the gap this replaces -- a
# substring check, which sat effectively at 1.0.
DUPLICATE_SIMILARITY = 0.88

# The name this component reports its health under. Not an agent, but it can
# stop the newsroom, so it is addressable by the alerting like one.
COMPONENT = "editorial_memory"

# How many neighbours to weigh. Only the nearest can be a duplicate, but seeing
# a couple more makes the log line diagnosable rather than an assertion.
NEIGHBOURS = 3


class EditorialMemoryAgent:
    """Enforces voice consistency and keeps the newsroom off repeated stories.

    Not an `Agent` subclass: it makes no model call and has no persona. It
    reads memory and decides, which is a service, and dressing it up as an
    agent would suggest it has judgement it does not have.
    """

    def get_or_create_memory(self) -> EditorialMemory:
        memory, _ = EditorialMemory.objects.get_or_create(
            id=1,
            defaults={
                'brand_voice': (
                    'Authoritative, forward-looking, technically grounded, '
                    'African-centric, and accessible.'
                ),
                'preferred_terminology': {
                    'AI': 'Artificial Intelligence',
                    'ML': 'Machine Learning',
                    'DevOps': 'Modern Engineering Practices',
                    'Teklora': 'Teklora Media & Solutions',
                },
                'excluded_topics': [],
            },
        )
        return memory

    def check_duplicate_coverage(self, title: str, summary: str = "") -> tuple[bool, str]:
        """Has this story been covered already?

        Raises `MemoryUnavailable` if the semantic half cannot run. That is
        deliberate: proceeding without the check is how the newsroom would
        publish the duplicate this exists to prevent, and a check that silently
        stops checking is worse than no check, because the pipeline goes on
        reporting that it looked.
        """
        exact = self._exact_match(title)
        if exact:
            return True, exact

        # Health is recorded here rather than inherited from `Agent.execute`,
        # because this is not an Agent -- it makes no model call. It still
        # halts the newsroom when it breaks, so it still has to page somebody:
        # without this, a dead embedding provider would stop every topic in the
        # cycle behind nothing but a log line.
        from ai_workflows.harness.alerts import record_failure, record_success
        from ai_workflows.harness.errors import AgentError

        try:
            verdict = self._semantic_match(title, summary)
        except AgentError as exc:
            record_failure(COMPONENT, exc)
            raise

        record_success(COMPONENT)
        return verdict

    @staticmethod
    def _exact_match(title: str) -> str:
        """The original substring check, kept for what it is good at."""
        existing = EditorialArticle.objects.filter(title__icontains=title[:20]).first()
        if existing:
            return (
                f"Title overlaps existing article '{existing.title}' "
                f"(#{existing.id})"
            )
        return ""

    def _semantic_match(self, title: str, summary: str) -> tuple[bool, str]:
        from ai_workflows.harness.memory import Memory

        query = f"{title}\n\n{summary}".strip()
        matches = Memory(scope="editorial").recall(
            query, kind="article", limit=NEIGHBOURS,
        )
        if not matches:
            return False, "Topic is original"

        nearest = matches[0]
        if nearest.score is not None and nearest.score >= DUPLICATE_SIMILARITY:
            return True, (
                f"Semantically matches '{nearest.title}' at "
                f"{nearest.score:.2f} similarity (threshold {DUPLICATE_SIMILARITY})"
            )

        logger.debug(
            "[editorial_memory] nearest coverage of '%s' is '%s' at %.2f",
            title, nearest.title, nearest.score or 0.0,
        )
        return False, "Topic is original"
