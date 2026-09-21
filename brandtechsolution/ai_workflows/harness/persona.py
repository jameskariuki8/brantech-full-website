"""Personas: who an agent is, declared once.

Every agent in this codebase currently carries two personas that disagree. A
rich role prompt at the top of the module -- "Chief Intelligence Officer at
Teklora", "Senior Editor-in-Chief at Teklora Media" -- and then, at the invoke
site, a second and much thinner SystemMessage that contradicts it: "You are an
expert tech journalism evaluation agent. Return ONLY raw JSON."

Two things are wrong with that. The halves disagree, and most of what the
second one does is beg for JSON -- which is the job of a structured-output
contract, not of a persona. So output format is deliberately not expressible
here. A Persona says who the agent is and how it behaves; the schema says what
shape the answer takes.
"""
from dataclasses import dataclass, field

# The company voice, shared by every agent. Today the writer gets this from
# EditorialMemory.brand_voice and the chat assistant has its own hardcoded
# version that never reads it, so the company has one brand voice and the
# codebase has two definitions of it. This is the default; step 2 replaces it
# with the stored profile so there is exactly one.
DEFAULT_VOICE = (
    "Authoritative, forward-looking, technically grounded, African-centric, "
    "and accessible."
)


@dataclass(frozen=True)
class Persona:
    """One agent's identity.

    Frozen because a persona changing at runtime would invalidate every cached
    step keyed on it, and because "who this agent is" is a declaration rather
    than state.
    """

    name: str
    role: str
    directives: tuple[str, ...] = ()
    voice: str = DEFAULT_VOICE

    # Anything the agent should refuse or avoid. Separate from directives so
    # the negative space is visible rather than buried in a list of thirty
    # instructions.
    constraints: tuple[str, ...] = ()

    def __post_init__(self):
        # Tuples, not lists: a frozen dataclass holding a mutable default is
        # frozen in name only, and these feed a cache key.
        object.__setattr__(self, "directives", tuple(self.directives))
        object.__setattr__(self, "constraints", tuple(self.constraints))

    def render(self) -> str:
        """The system message text.

        Ordering is not cosmetic. This string is the front of the cached
        prefix, so everything here must be stable across requests -- no
        timestamps, no per-request ids, nothing derived from the turn.
        """
        parts = [f"You are {self.role}."]

        if self.voice:
            parts.append(f"\nVoice: {self.voice}")

        if self.directives:
            parts.append("\nHow you work:")
            parts.extend(f"- {directive}" for directive in self.directives)

        if self.constraints:
            parts.append("\nWhat you must not do:")
            parts.extend(f"- {constraint}" for constraint in self.constraints)

        return "\n".join(parts)

    def fingerprint(self) -> str:
        """A stable digest of this persona, for cache keys.

        Steps are content-addressed on their inputs *and* the agent version,
        so that editing a persona invalidates the cached results it produced.
        Without that, prompt work would appear to do nothing -- a genuinely
        miserable thing to debug.
        """
        import hashlib

        return hashlib.sha256(self.render().encode("utf-8")).hexdigest()[:16]

    def with_voice(self, voice: str) -> "Persona":
        """This persona speaking in a different voice.

        Used by the profile layer to push the stored brand voice into every
        agent, so the voice lives in one place and the persona only says what
        is specific to that agent.
        """
        return Persona(
            name=self.name,
            role=self.role,
            directives=self.directives,
            voice=voice,
            constraints=self.constraints,
        )
