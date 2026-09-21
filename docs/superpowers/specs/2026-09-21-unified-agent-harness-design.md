# Unified Agent Harness — Design

**Date:** 2026-09-21
**Status:** Draft, awaiting approval

## Goal

Collapse the two unrelated agent systems into one framework, so that every
agent draws its model access, memory, tools, persona and failure behaviour
from the same place. One orchestrator routes to subagents; each subagent
keeps its own control flow.

The target is not "make everything agentic". It is to delete the repetition,
give memory a single vectorised home, and make a missing API key a loud
failure rather than a quiet fabrication.

## Problem

There are two agent systems in the codebase and they share nothing.

**One** is the chat assistant, `ai_workflows/service.py`. It is a LangGraph
`create_react_agent` (`service.py:265`) over Gemini, with three tools and a
real persisted checkpointer (`service.py:205`). It is the better-built of the
two and nothing else uses any part of it.

**The other** is the newsroom, `editorial/orchestrator.py:31`. It instantiates
fourteen service classes across nine apps and calls them in a fixed sequence.
Six of those call a model. Each one builds its own client, parses its own
response, and invents its own failure behaviour.

### The repetition is mechanical

Six copies of the same model construction, differing only in temperature:

| Agent | Site | Temperature |
|---|---|---|
| Trend intelligence | `trends/services/intelligence.py:53` | 0.2 |
| Trend prediction | `trends/services/prediction.py:48` | 0.4 |
| Research investigator | `research/services/investigator.py:66` | 0.3 |
| Fact verifier | `research/services/fact_verifier.py:50` | 0.1 |
| Article writer | `editorial/services/writer.py:70` | 0.4 |
| Social/multi-platform | `editorial/services/social.py:75` | 0.4 |

Every one is wrapped in `try/except` that sets `self.model = None`. Every one
is followed, later in the same file, by the identical dance: strip an optional
` ``` ` fence, `json.loads(..., strict=False)`, catch everything, return a
canned dict. Those six fence-strips live at `intelligence.py:126`,
`prediction.py:72`, `investigator.py:122`, `fact_verifier.py:98`,
`writer.py:141`, `social.py:128`.

Changing the model, adding a retry, setting a timeout, or adding a token
budget currently means editing six files and hoping none was missed.

### Memory is in three places that do not know about each other

1. **Episodic.** `DjangoCheckpointer` (`ai_workflows/checkpointer.py:23`) over
   `ConversationThread` / `ConversationCheckpoint`. Works well. Chat only.
2. **Profile.** `EditorialMemory` (`editorial/models.py:145`) — a singleton row
   holding brand voice, terminology and excluded topics. Editorial only.
3. **Semantic.** `KnowledgeDocument` (`knowledge_base/models.py`) — a proper
   pgvector store with `index_document` and `semantic_search`. Barely used.

The clearest symptom: `EditorialMemoryAgent.check_duplicate_coverage`
(`editorial/services/memory.py:33`) is supposed to stop the newsroom covering
the same story twice. It does this with
`EditorialArticle.objects.filter(title__icontains=title[:20])` — a substring
match on the first twenty characters — while a semantic vector store capable
of answering that question properly sits unused one app away. The orchestrator
trusts its verdict at `orchestrator.py:98` and rejects topics on it.

### Vectors go stale by design

`BlogPost.embedding` and `Project.embedding` are only ever written by the
management command `ai_workflows/management/commands/init_vector_stores.py`
(lines 43-44 and 77-78). There is no save hook. Edit a blog post in the panel
and its vector still describes the previous version until somebody remembers
to re-run the command by hand. Only `KnowledgeDocument` is kept current, and
only for published articles, via `index_article_embeddings_task`.

### Every agent has two personas that disagree

Each of the six carries a rich role prompt — "Chief Intelligence Officer at
Teklora" (`intelligence.py:19`), "Senior Editor-in-Chief at Teklora Media"
(`writer.py:18`), "Lead Fact Verification Editor" (`fact_verifier.py:17`), and
so on. Then, at the invoke site, each passes a *second* and much thinner
`SystemMessage` that contradicts it: "You are an expert tech journalism
evaluation agent. Return ONLY raw JSON." (`intelligence.py:120`), "You are an
award-winning tech journalist. Return ONLY raw JSON." (`writer.py:137`).

So the persona is split in two, the halves disagree, and most of what the
system message actually does is beg for JSON — which is the job of a
structured-output contract, not of a persona.

Meanwhile the chat assistant's persona is a third thing entirely: a hardcoded
`SYSTEM_PROMPT_TEMPLATE` (`service.py:88`) that never reads
`EditorialMemory.brand_voice`. The company has one brand voice and the
codebase has two definitions of it that cannot drift into agreement.

### Tools are chat-only

`ai_workflows/tools.py` defines three tools: `search_blog_posts` (`:150`),
`search_projects` (`:163`) and a per-user info tool (`:176`). All three are
bound to the chat assistant and nothing else. The six newsroom agents have no
tools at all — the research agent cannot search the knowledge base its own
pipeline populates.

### Failure is silent and fabricates

Because every agent degrades to a canned draft, a deployment with a missing or
rotated API key does not fail. It publishes. `writer.py`'s fallback emits
confident filler including invented figures — *"Representative enterprise
deployments demonstrate a 40% improvement in performance."* — straight into a
reviewable draft, indistinguishable from model output.

This is not hypothetical. It is what hid the `BlogPost.title` overflow fixed in
`3648418`: the newsroom test passed when the network was down (fallback, short
title) and failed when it was up (real model, long title), so neither result
carried information.

## Decisions

Settled with the user on 2026-09-21:

1. **Deterministic spine.** The orchestrator routes between *agents*. Each
   agent keeps its own control flow. Editorial's eleven stages stay a fixed
   sequence and `EditorialPipelineRun` stage tracking keeps its meaning. No
   LLM decides what runs next.
2. **Fail loudly.** A missing, unreachable or incoherent model raises. The run
   is marked failed and surfaced. No canned prose is ever written to an
   article. This reverses today's behaviour deliberately.
3. **One framework, no duplication.** Model access, response parsing, retry,
   memory, tools and personas each have exactly one implementation.
4. **Explicit LLM touch points.** Provider wiring is confined to named seams,
   so swapping or adding a model is a change in one file.
5. **Vectorised memory by default.** Writing to memory embeds it; callers do
   not opt in.
6. **Shared tool management, per-agent suites.** One registry, one definition
   per tool; each agent declares the suite it is issued.
7. **One persona per agent, first-class.** A single declared persona per agent,
   composed from a shared brand voice. No second contradicting system message.

## Architecture

```
ai_workflows/harness/
    llm.py          model access, the only provider touch point
    contract.py     prompt -> validated object; the only parser
    memory.py       the unified memory facade
    tools.py        registry + per-agent suites
    persona.py      persona composition from shared brand voice
    base.py         Agent contract
    registry.py     name -> agent
    errors.py       the failure taxonomy

ai_workflows/orchestrator.py    the single supervisor
```

Agents themselves stay in their current apps. This is a harness they plug
into, not a new home for their logic — `editorial/services/writer.py` remains
the writer, it just stops building its own client.

### LLM touch points (`harness/llm.py`)

One module constructs model clients. Nothing else imports
`langchain_google_genai`.

```python
class ModelRole(str, Enum):
    PRECISE   = "precise"     # temperature 0.1 — verification, extraction
    ANALYTIC  = "analytic"    # 0.2-0.3 — scoring, research
    CREATIVE  = "creative"    # 0.4 — drafting, social
    CONVERSATIONAL = "conversational"  # chat

def get_model(role: ModelRole, *, tools=None) -> BaseChatModel
def get_embedder() -> Embeddings
```

Roles rather than raw temperatures: the six current values are really four
intentions, and naming the intention means a future model swap re-tunes in one
place. Timeout, retry, token budget and tracing attach here, once.

`get_model` raises `ModelUnavailable` if the provider cannot be constructed. It
never returns `None` — the `self.model = None` pattern is what made silent
degradation possible, so the type makes it unrepresentable.

**Provider seam.** `llm.py` is the only file naming a vendor. Adding a second
provider means adding a branch here and nothing else. Model identifiers keep
coming from `brandtechsolution/config.py`, which already holds
`gemini_chat_model` and `gemini_embedding_model`.

### The prompt contract (`harness/contract.py`)

One function replaces six copies of the fence-strip:

```python
def ask(
    persona: Persona,
    prompt: str,
    schema: type[BaseModel],
    *,
    role: ModelRole,
    retries: int = 1,
) -> BaseModel
```

It renders the persona as the system message, calls the model, strips a fenced
block if present, parses, and validates against a Pydantic schema. On invalid
JSON or a schema mismatch it retries once with the validation error appended,
then raises `AgentOutputInvalid`.

This kills the "Return ONLY raw JSON" instruction in all six agents: the
requirement moves into the contract, where it can be enforced rather than
requested. Each agent's expected shape becomes a declared Pydantic model —
`ArticleDraft`, `TrendScores`, `VerificationAudit` — instead of a prose
description in a prompt and a pile of `.get(key, default)` at the call site.

Those schemas double as documentation of what each agent actually returns,
which today can only be discovered by reading the `.get` calls.

### Unified memory (`harness/memory.py`)

Three layers behind one facade, because they answer genuinely different
questions:

| Layer | Question | Store | Status |
|---|---|---|---|
| Episodic | "what happened in this thread?" | `ConversationThread` / `ConversationCheckpoint` | exists, generalise |
| Semantic | "what do we already know about X?" | `KnowledgeDocument` + pgvector | exists, adopt properly |
| Profile | "how do we speak and what do we avoid?" | `EditorialMemory` → `AgentProfile` | exists, generalise |

```python
class Memory:
    def remember(self, text, *, kind, metadata=None) -> MemoryRecord
    def recall(self, query, *, kind=None, limit=5) -> list[MemoryRecord]
    def thread(self, thread_id) -> Checkpointer
    def profile(self) -> AgentProfile
```

**Vectorised by default.** `remember()` embeds on write. There is no
`embed=True` flag, because an optional embedding is how the current stores
drifted apart. Embedding happens in a Celery task on commit — the pattern
`index_article_embeddings_task` already establishes — so a slow embedding
never blocks a request, and a failing one retries with backoff rather than
being swallowed.

**Closing the stale-vector gap.** `BlogPost` and `Project` get their
embeddings refreshed on save through the same queued path, replacing the
manual `init_vector_stores` command as the only way vectors get written. The
command stays, for backfill.

**What sharing buys.** The chat assistant can answer from research dossiers it
has never seen today. `check_duplicate_coverage` becomes a semantic query
against everything the company has published instead of a twenty-character
substring match. A new agent gets all of this by existing.

### Tool management (`harness/tools.py`)

One registry, one definition per tool, suites assembled per agent:

```python
registry.register("search_knowledge", search_knowledge)
registry.register("search_blog_posts", search_blog_posts)
...

SUITES = {
    "assistant":  ["search_blog_posts", "search_projects", "user_info"],
    "research":   ["search_knowledge", "search_blog_posts", "fetch_url"],
    "writer":     ["search_knowledge"],      # prior coverage, for continuity
    "verifier":   ["search_knowledge", "fetch_url"],
    "intelligence": ["search_knowledge"],
}
```

Each agent declares `tool_suite` and the harness binds it. The existing three
tools move into the registry unchanged.

This is where the newsroom gains something it has never had. The fact verifier
currently verifies from the model's own weights; with `fetch_url` and
`search_knowledge` it can check a claim against the sources in the dossier and
against what the company has already verified. That is a capability change,
not just a refactor, and it should land behind its own review.

### Personas (`harness/persona.py`)

A persona is declared once per agent and composed, not duplicated:

```python
@dataclass(frozen=True)
class Persona:
    name: str            # "Fact Verification Editor"
    role: str            # what this agent is for
    directives: list[str]
    voice: str = ""      # defaults to the shared brand voice

    def render(self) -> str
```

The shared `voice` comes from `AgentProfile` — the generalised
`EditorialMemory.brand_voice` — so the chat assistant and the writer speak with
one voice for the first time. Output-format instructions are **not** part of a
persona; they belong to the schema in `contract.ask`.

Migration is mostly relocation: the six existing role prompts
(`intelligence.py:19`, `prediction.py:17`, `investigator.py:19`,
`fact_verifier.py:17`, `writer.py:18`, `social.py:18`) become `Persona`
declarations, and the six contradicting `SystemMessage` lines are deleted.

### The agent contract (`harness/base.py`)

```python
class Agent(ABC):
    name: str
    persona: Persona
    model_role: ModelRole
    tool_suite: str | None = None
    memory_scope: str

    def run(self, request: AgentRequest) -> AgentResult
```

`run` is the only entry point the orchestrator knows. Everything inside it is
the agent's own business — which is what keeps editorial's fixed sequence
legal under this design.

### The orchestrator (`ai_workflows/orchestrator.py`)

One supervisor. It resolves a request to an agent by name, or by a cheap
classification step for free-text input, opens or resumes the shared thread,
invokes `agent.run(...)`, and records the outcome.

```
orchestrator.dispatch(request)
    ├── assistant    react loop + tools      (conversational)
    ├── editorial    fixed 11-stage pipeline (wraps today's orchestrator)
    ├── research     dossier synthesis       (also callable as a tool)
    └── trends       discovery and scoring
```

`EditorialPipelineOrchestrator` is not deleted. It becomes the body of the
editorial agent's `run()`, keeping its `on_stage` callback and its
`EditorialPipelineRun` row. From the supervisor's side it is one agent; inside,
it is the same deterministic sequence it is today.

**Naming.** Today's `EditorialPipelineOrchestrator` and the new orchestrator
would otherwise both be "the orchestrator". The existing class is renamed
`EditorialPipeline` to keep the word unambiguous.

### Failure policy (`harness/errors.py`)

```
AgentError
├── ModelUnavailable      provider missing or unreachable
├── AgentOutputInvalid    unparseable or schema-violating after retry
├── ToolFailed            a bound tool raised
└── MemoryUnavailable     the store is down
```

Nothing is caught and converted to canned content. A stage that raises fails
its `EditorialPipelineRun` with the reason, and the dashboard shows it. The
fourteen `_fallback_*` methods are deleted.

Two consequences to accept deliberately:

- A newsroom run with no API key now produces **nothing** instead of a bad
  draft. That is the point.
- The chat assistant must degrade differently from the pipeline: a user asking
  a question deserves "I can't reach my tools right now", not a stack trace.
  So `ModelUnavailable` is caught at the *edge* — the chat view — and rendered
  as a message. It is never caught at the agent layer.

## What each existing piece becomes

| Today | After |
|---|---|
| `ai_workflows/service.py` `ChatAssistant` | `AssistantAgent`, react loop kept, model/memory/tools/persona from harness |
| `ai_workflows/checkpointer.py` | unchanged, becomes the episodic layer |
| `ai_workflows/agents.py` (deprecated shim) | deleted |
| `editorial/orchestrator.py` | `EditorialPipeline`, body of `EditorialAgent.run()` |
| 6 LLM services | keep their logic; lose client construction, parsing and fallbacks |
| 8 non-LLM services (SEO, publisher, analytics, …) | untouched — they are deterministic Python and not agents |
| `editorial/services/memory.py` | folded into `harness/memory.py`; dedup becomes semantic |
| `knowledge_base/services/knowledge_graph.py` | becomes the semantic layer's implementation |
| `ai_workflows/tools.py` | tools move into the registry |

Note the eight non-LLM "agents" are explicitly *not* migrated. The SEO
"agent" builds a JSON-LD dict and the publisher copies fields into a
`BlogPost`; calling them agents was always generous, and dragging them through
a model harness would add cost and failure modes for nothing.

## Migration order

Each step ships and is green before the next starts.

1. **Harness, no callers.** `llm`, `contract`, `errors`, `persona`, `base`.
   Unit-tested against the existing fakes. Nothing else changes.
2. **Memory unification.** Facade over the three stores, vectorise-on-write,
   save hooks for `BlogPost`/`Project`. Behaviour-compatible; the substring
   dedup stays until step 4.
3. **Tools.** Registry plus suites; the chat assistant switches to the registry
   for its existing three. No new tools yet.
4. **Editorial onto the harness.** Six agents lose their clients, parsers and
   fallbacks; personas declared; schemas declared; dedup becomes semantic.
   This is the step that deletes the most code and changes failure behaviour.
5. **Assistant onto the harness.** Persona from shared voice; model from `llm`.
6. **Orchestrator.** Supervisor, registry, dispatch. Until this lands the
   agents are already unified — the orchestrator is the last piece, not the
   first.
7. **New tools for the newsroom** (`fetch_url`, `search_knowledge` for the
   verifier). Separate review; this changes what the agents can do.

Steps 1-3 are additive and safe. Step 4 is the sharp one.

## Testing

`editorial/llm_fakes.py` (added in `3648418`) already stubs the model across
all six modules and is the foundation. It moves to
`ai_workflows/harness/testing.py` and stubs at the single `llm.get_model` seam
instead of six patch targets — which is itself an argument for the design, as
the fake currently has to know all six module paths.

- Harness units: role→config mapping, fence-strip, schema retry, each error.
- **Fallback removal is asserted:** with the model unavailable, a pipeline run
  must fail and write nothing. Today the equivalent test would assert a canned
  draft exists.
- Memory: `remember` embeds; `recall` returns by similarity, not substring; a
  `BlogPost` edit refreshes its vector.
- Persona: rendered prompt contains the shared brand voice and no
  output-format instruction.
- Tools: an agent is bound its declared suite and nothing else.
- The eighteen editorial tests stay green throughout, unchanged where possible
  — they are the regression net for steps 4-6.

## Out of scope

- Multi-provider support. The seam is designed for it; only Gemini is wired.
- Making the eight deterministic services agentic.
- Replacing Celery for agent scheduling.
- Streaming responses.
- Re-tuning any prompt's content. Personas are relocated verbatim; changing
  what they say is a separate, reviewable change.

## Open risks

**The reversal is user-visible.** Today a broken key yields a mediocre draft;
after step 4 it yields a failed run. If the newsroom has been quietly running
on fallbacks, this will look like a new outage rather than a newly visible one.
Worth checking the fallback rate in logs before shipping step 4.

**Embedding cost and quota.** Vectorise-on-write adds Gemini embedding calls on
every `BlogPost`/`Project` save. Queued and debounced, but it is new spend
against the same quota the newsroom uses.

**The 3072-dimension commitment.** All four vector columns are 3072-wide for
`gemini-embedding-001`. A provider swap means a migration and a full re-embed.
The seam does not rescue that; nothing short of a dimension-agnostic store
would.

**Semantic dedup will behave differently.** Replacing a substring match with
similarity will reject topics the current check waves through, and vice versa.
The threshold needs tuning against real topics, and should be configurable
rather than baked in.

**Stale prompt content.** The assistant's system prompt
(`service.py:88`) still uses the deleted "Test Project" row as its worked
example. Relocating personas verbatim would preserve that. Flagged for the
implementer to fix in passing.
