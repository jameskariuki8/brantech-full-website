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
2. **Fail loudly, and tell someone.** A missing, unreachable or incoherent
   model raises. The run is marked failed, and the failure is mailed to the
   capability holders rather than left on a dashboard nobody is watching. No
   canned prose is ever written to an article. This reverses today's behaviour
   deliberately.
3. **One framework, no duplication.** Model access, response parsing, retry,
   memory, tools and personas each have exactly one implementation.
4. **Explicit LLM touch points, five key-based providers plus Codex.**
   OpenRouter, OpenAI, Anthropic, Gemini and DeepSeek activate when a valid key
   is present and verified; Codex is OAuth and subscription-billed, built but
   off by default. Provider wiring is confined to `harness/llm.py`. Model
   identities, capabilities and prices come from a refreshed catalogue rather
   than from constants.
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
    alerts.py       health state + capability-addressed alerting

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

**Provider seam.** `llm.py` is the only file naming a vendor. Model identifiers
stop being hardcoded and come from the catalogue below; `config.py` keeps
`gemini_chat_model` and `gemini_embedding_model` as the pinned defaults.

## Providers

Five providers authenticate with an API key. A sixth, Codex, authenticates
differently and carries a caveat worth reading before it is enabled.

| Provider | Auth | Billed against | Chat endpoint |
|---|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | usage | `https://openrouter.ai/api/v1` |
| OpenAI | `OPENAI_API_KEY` | usage | `https://api.openai.com/v1` |
| Anthropic | `ANTHROPIC_API_KEY` | usage | `https://api.anthropic.com/v1` |
| Gemini | `GOOGLE_API_KEY` (already present) | usage | `https://generativelanguage.googleapis.com/v1beta` |
| DeepSeek | `DEEPSEEK_API_KEY` | usage | `https://api.deepseek.com` |
| Codex | ChatGPT OAuth | **subscription seat** | Responses API, via OAuth token |

### Codex: real, but not a drop-in sixth provider

The mechanism exists and works. `codex login` runs a browser OAuth flow and
writes access and refresh tokens to `~/.codex/auth.json` (or the OS keyring,
per `cli_auth_credentials_store`), and several community proxies —
`dvcrn/codex-oauth-proxy`, `wowyuarm/codex-proxy` — re-expose those
credentials as an OpenAI-compatible endpoint, serving requests against
ChatGPT Plus/Pro subscription quota rather than API credits. The traffic goes
to the **Responses API**, not chat-completions, which is why some proxies
support it and some do not.

What makes this different from the other five is not technical. OpenAI's own
Codex authentication documentation says to *"use API key authentication for
programmatic Codex CLI workflows, such as CI/CD jobs"*, and states that
ChatGPT subscription credentials are not intended for direct server-side API
requests. The supported headless path (device-code auth) is for running the
**CLI** without a browser — not for a server answering requests on the
subscription's behalf.

That is a business decision, not a technical one, so the design makes it an
explicit, off-by-default choice rather than quietly wiring it in:

- Modelled as a provider with `auth_mode = OAUTH` and
  `billing = SUBSCRIPTION`, so it is visibly not the same kind of thing as an
  API-key provider.
- **Never in the default preference order.** An agent gets Codex only if an
  operator puts it there, and the panel says what that means.
- **Excluded from unattended work by default.** The newsroom runs overnight on
  Beat with nobody watching; a subscription seat is rate-limited per human, so
  a pipeline on Codex will hit limits and, worse, a failure there is a failure
  of someone's personal account. Interactive and development use is the
  sensible ceiling.
- **Cost reporting shows it as seat-consuming, not billable.** A run served by
  Codex has no per-token price, so `AgentInvocation` records zero cost with
  `price_source = UNKNOWN` rather than implying the run was free.
- **Token custody is the real risk.** Refresh tokens must rotate, and anything
  that can reach the endpoint spends the subscription — the proxies bind to
  `127.0.0.1` for exactly that reason. A Django app holding a long-lived
  ChatGPT refresh token is a materially worse secret to leak than an API key,
  because it is an account credential rather than a scoped, revocable,
  spend-capped one.

My recommendation is to build the seam and leave Codex off: keep it available
for local development, where it genuinely saves money, and keep production and
the newsroom on API keys. But the mechanism is real, you asked for it, and the
constraint is a policy one — so it is yours to decide, and the design supports
either answer without a rewrite.

### Activation on a valid key

Three states, because "a key is present" and "a key works" are different
things, and conflating them is how a typo becomes a silent outage:

```
absent     no key in config
candidate  key present, never validated or last probe failed
active     key present and the provider answered its model list
```

Validation calls the provider's model-list endpoint — the cheapest
authenticated call each one has, and the same call the catalogue refresh
needs, so activation and catalogue refresh are one operation.

Three rules about *when*:

- **Never at import time.** `config.py` is imported by `settings.py`; a network
  call there would make Django's startup depend on five third parties. A
  provider with a key starts as `candidate` and is promoted by the first
  refresh.
- **Never in the request path.** Probing per request doubles latency and burns
  rate limit. State lives in a `Provider` row with `last_checked_at`.
- **On a Beat schedule**, alongside the catalogue refresh, plus on demand from
  the panel so adding a key does not mean waiting for the next tick.

A Django system check reports which providers resolved, following the
precedent `mailgun.check_email_configured` and `turnstile.py` already set in
this codebase — a deployment should not have to guess whether its keys took.

### Where model metadata and pricing actually come from

This is the part worth reading before building anything, because the obvious
assumption is wrong. **Only one of the five publishes pricing through its
API.** Verified against the live endpoints on 2026-09-21:

| Provider | List endpoint | Auth to list | Pricing in response | Other metadata |
|---|---|---|---|---|
| OpenRouter | `GET /api/v1/models` | **none** | **yes** — `pricing.prompt`, `pricing.completion`, per token, as strings | `context_length`, `architecture`, `supported_parameters`, `top_provider`, `knowledge_cutoff`, `expiration_date` |
| OpenAI | `GET /v1/models` | yes | no | `id`, `object`, `created`, `owned_by` — nothing else |
| Anthropic | `GET /v1/models` | yes | no | `id`, `display_name`, `created_at`, `max_input_tokens`, `max_tokens`, `capabilities` |
| Gemini | `GET /v1beta/models` | yes | no | `inputTokenLimit`, `outputTokenLimit`, `supportedGenerationMethods`, `thinking`, default sampling params |
| DeepSeek | `GET /models` | yes | no | `id`, `object`, `owned_by` |

OpenRouter's catalogue is unauthenticated, covers the other four providers'
models under `anthropic/…`, `openai/…`, `google/…`, `deepseek/…`, and carries
prices and deprecation dates for all of them. That makes it the obvious
metadata source — and it should be used as one — but the ceiling has to be
stated plainly:

> **OpenRouter's prices are OpenRouter's prices.** They are what OpenRouter
> charges to proxy a model, which need not equal what the provider charges you
> directly. Treating them as first-party rates is an approximation, close
> enough to choose a model by and **not** good enough to bill anyone from.

So the catalogue records provenance per row rather than pretending one number
is authoritative:

```python
class PriceSource(str, Enum):
    PROVIDER = "provider"     # the provider's own API said so
    OPENROUTER = "openrouter" # derived from OpenRouter's listing
    MANUAL = "manual"         # checked-in table, with an as_of date
    UNKNOWN = "unknown"
```

Every price carries its source and `price_checked_at`. Anything shown as money
in the panel shows its provenance next to it. A `MANUAL` row older than its
staleness window is rendered as stale rather than quietly trusted — a wrong
price presented confidently is worse than a missing one.

Direct-provider prices come from a checked-in `harness/pricing.toml` seeded
with an explicit `as_of` date, so a fresh deployment has usable numbers before
the first refresh and it is obvious when they were last touched by a human.
The Anthropic rates for that seed are in this skill-cached table and on the
published pricing page; OpenAI, Gemini and DeepSeek publish theirs on their
pricing pages only. None of it is scrape-able reliably, which is the honest
reason the manual table exists.

### The catalogue

```python
class CatalogueEntry(models.Model):
    provider, model_id, display_name
    context_tokens, max_output_tokens
    input_price_per_mtok, output_price_per_mtok
    price_source, price_checked_at
    capabilities          # JSON: tools, vision, json_mode, thinking
    deprecated_at         # OpenRouter's expiration_date, where known
    available             # last refresh saw it
    refreshed_at
```

Refreshed by a Beat task on a daily cadence — model lists move in weeks, not
minutes, and a daily pull is five cheap calls. The task is additive: a model
that disappears from a listing is marked `available=False`, never deleted,
because historical invocation rows point at it.

### Resolving a role to a model

`ModelRole` stops meaning "a temperature" and starts meaning "a requirement".
Resolution order, first match wins:

1. An explicit pin for that agent, if set. Always wins.
2. The configured provider preference order, filtered to `active` providers.
3. Within a provider, the model mapped to that role.

A provider failure (rate limit, 5xx, timeout) falls through to the next
candidate and records which model actually served the call. An agent that must
not fail over — a verifier whose output is compared across runs, say — can
declare `allow_fallback = False` and get `ModelUnavailable` instead.

### Spend becomes visible

Pricing in the catalogue is what makes this possible, and it is arguably worth
more than the provider choice. Each call records an `AgentInvocation`: agent,
provider, model, prompt and completion tokens, computed cost, the run it
belonged to. The newsroom's cost per published article becomes a number.

`celery.py` already says the pipeline must not "double-spend model quota" as
its reason for not auto-retrying lost runs. That constraint is currently
enforced by reasoning about it; with invocation rows it can be measured.

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

### Changing the embedding model

Switching embedding model is not a config change, because vectors from two
models are not comparable — a cosine score between them is a number with no
meaning. The failure mode is the dangerous kind: nothing errors, search just
quietly returns worse results. So the switch is a migration with a designed
shape.

**Vectors belong to a space, and spaces never mix.**

```python
class EmbeddingSpace(models.Model):
    provider, model_id, dimensions
    status          # building | active | retired
    created_at, activated_at
```

Every stored vector references its space. Changing model **creates a new
space** and backfills into it; it never overwrites in place. The old space
keeps serving every query until cutover, so search quality is unchanged
throughout the migration rather than degrading as rows are converted. Cutover
is one atomic flip of which space is `active`, and the old space is retired,
not deleted — rollback is another flip until someone reclaims the storage.

Querying across two spaces and merging by score is **not** an option, however
tempting it looks: the scores are not on a shared scale, so the merge is
arbitrary. Half-migrated means "serve entirely from the old space", always.

**Re-embedding is scored, not sequential.** Re-embedding everything at once is
the expensive way to do it, and most of the spend buys nothing — the long tail
of documents is never retrieved. The backfill works a priority queue:

```python
importance = (
    w_retrieval * recent_retrieval_rate     # what the system actually uses
  + w_engagement * normalised_engagement    # views, likes, comments
  + w_recency   * recency_decay
  + w_flag      * (featured or pinned)
)
```

Signals already in the schema: `BlogPost.view_count`, `featured`, `status`,
the `BlogLike` and `BlogComment` relations, `Project.featured` and
`commit_count`, `KnowledgeDocument.doc_type`.

The strongest signal is the one that does not exist yet: **how often a
document is actually retrieved.** Nothing records that today. `Memory.recall()`
is the single chokepoint through which every semantic lookup passes once the
facade lands, so it increments a counter on what it returns. After a few weeks
that counter says which documents matter far better than view counts do,
because it measures what the agents use rather than what humans clicked. It is
worth adding in step 2 purely so this data exists by the time a switch is
wanted.

**The tail is never bulk-embedded at all.** Below an importance floor,
documents are left unembedded in the new space and converted **lazily, on
first retrieval need**. If a document is never needed again, it is never paid
for. This is the single biggest saving in the design, and it costs one
cache-miss path in `recall()`.

**Pacing.** The backfill is a Beat-driven drip, not a loop:

- **Batch.** Embedding APIs take arrays; one call for N documents removes N-1
  round trips. Batch size is capped by the provider's input limit.
- **Budget.** A configured daily ceiling in tokens or currency, priced from the
  catalogue. When the day's budget is spent the task stops and resumes at the
  next window — the migration takes longer and never surprises anyone with a
  bill.
- **Off-peak.** The bulk runs overnight, where
  `release_stale_pipeline_runs_task` already sits at 02:30 EAT. High-importance
  rows are exempt and go immediately.
- **Backpressure.** A 429 backs off and lowers the batch size rather than
  retrying at the same rate. Embedding quota is shared with the newsroom, and a
  migration must not starve live work.
- **Idempotence.** Each row stores a content hash; an unchanged document
  already present in the target space is skipped, so a restarted or
  overlapping run costs nothing.

**Progress is visible.** The migration reports importance-weighted coverage,
not row count — "94% of retrieval volume, 31% of rows" is the number that says
whether cutover is safe. Cutover is offered when weighted coverage passes a
threshold, and it stays a human decision.

This is also why `get_model` and `get_embedder` resolve independently. Chat can
fail between five providers freely; embeddings change on this path or not at
all.

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

### Alerting

Failing loudly is only loud if somebody hears it. A failed run that is visible
only on `/editorial/dashboard/` is visible only to whoever happens to open it,
which for an overnight Beat run is nobody.

The transport for this already exists and is trustworthy: `send_mail` over the
Mailgun backend, with `mailgun.check_email_configured` refusing to boot in
production if mail would go to the console. What does **not** exist is any
health alert — all six current `send_mail` sites are transactional
notifications (invitations, review-ready, inquiries, bookings). This design
adds the first one.

**Address by capability, not by config.** `staff/emails.py:capability_holder_emails`
already solves the recipient problem: it resolves a capability codename to the
staff accounts that hold it, counting direct grants, role groups and
superusers. `approval/services/workflow.py:58` uses it to reach whoever holds
`publish_blog`. Alerts use the same helper, so who gets paged is changed by
granting a capability in the panel rather than by editing an environment
variable.

That requires one new capability, because none of the twelve in
`staff/capabilities.py` means "operations":

```python
("receive_alerts", "Receive system health alerts"),   # Administration group
```

A new codename rather than reusing `manage_staff`: the people who should be
woken by a dead pipeline are not necessarily the people who administer
accounts, and conflating them means the only way to stop being paged is to
give up an unrelated permission.

**Alert on state change, not per failure.** A dead provider fails every stage
of every run. Sending one message per failure turns an outage into a mail
storm, and the storm is worse than the silence it replaced. So:

- The first transition from healthy to failing sends one alert.
- Further failures of the same agent with the same error class are recorded
  and suppressed.
- Recovery sends one "resolved" message.

State lives in a small `AgentHealth` row per agent — last status, last error
class, the count suppressed since the alert, and when it was sent. It also
gives the dashboard something honest to render.

**Send directly, never through the campaign outbox.** An alert is
transactional and urgent; the outbox is drained on a Beat interval and is for
bulk. `staff/emails.py:send_invitation` already documents exactly this
reasoning, and the same applies with more force here.

**`fail_silently=False`.** The approval workflow passes `fail_silently=True`,
which is defensible for a review notice — the draft is still on the dashboard.
It is not defensible for an alert, where a swallowed send means the failure is
silent again by a different route. A failed alert is logged at `ERROR` and
recorded against the `AgentHealth` row.

**Themed HTML, not a wall of text.** The machinery for this already exists and
is, again, used by exactly one part of the system. `messaging/emailhtml.py`
inlines `BASE_EMAIL_CSS` because Outlook and Gmail ignore `<style>` blocks;
`messaging/rendering.py:29` converts HTML to a plain-text alternative; the
outbox sends both halves with `EmailMultiAlternatives` and
`attach_alternative(..., "text/html")`
(`messaging/management/commands/process_email_outbox.py:162`). All of it is
wired to campaigns only. Every transactional message in the codebase —
invitations, review-ready, task notices, inquiry and booking confirmations —
is plain text.

So the alert layer introduces a small shared shell rather than a second email
stack:

```
brandtechsolution/mail/
    shell.py        render(template, context) -> (html, text)
    templates/mail/
        _base.html      branded shell: header, content slot, footer
        alert.html      agent failure / recovery
```

Three things it must do, each for a reason the existing code already
documents:

- **Inline the CSS.** Reuse `inline_email_css`. A system email that renders as
  unstyled text in Outlook is worse than one that was never themed, because
  it looks broken rather than plain.
- **Always send a text alternative,** built with the existing `html_to_text`.
  An alert is the last message that should be unreadable in a client that
  refuses HTML, and some on-call paths are text-only.
- **Do not sanitise.** `sanitize_email_html` exists because campaign bodies are
  *authored by users*. System templates are ours, and running them through nh3
  would silently strip the table-based layout that email clients actually
  need. Sanitising is for untrusted input; this is not that.

The shell is deliberately not in `messaging/`. That app is the bulk campaign
system, with an outbox, suppressions and unsubscribe semantics that have
nothing to do with a transactional alert — and an alert must never acquire an
unsubscribe link or be filtered by a suppression list. It borrows
`emailhtml`'s two functions and owns its own templates.

Theme follows the site: `#050811` header, `#00FF94` for recovery, a red for
failure, brand blue `#007AFF` for links, which `BASE_EMAIL_CSS` already uses.
Content stays severe — agent, error class, when it started, how many
occurrences were suppressed, and a deep link to the run. An alert is read on a
phone at an awkward hour; it should be scannable in one screen.

**Beyond alerts.** The same shell is what the five existing plain-text notices
should use, and they would each become a template with no change to their send
logic. Worth doing, but it is a separate change with its own review — it
touches mail people already rely on, and bundling it here would put a cosmetic
refactor inside a reliability one.

**The honest limit.** An email alert cannot report a mail outage. If Mailgun
is the thing that is down, nothing here fires, and the only signal is the
dashboard and the logs. Covering that needs a channel that does not share a
dependency with the thing it monitors — out of scope here, but worth naming
so it is not mistaken for covered. `ApprovalNotification.channel` already
anticipates multiple channels, and the same shape would extend to a webhook.

This materially de-risks the migration. Step 4's reversal — runs that used to
produce a mediocre draft now produce nothing — is safe to ship precisely
because the failure reaches a person the first time it happens, rather than
waiting to be discovered. With five providers configured it is also less
likely: a rate limit on one is a fallback, not an outage.

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
3. **Providers and the catalogue.** `Provider` and `CatalogueEntry`, the
   refresh task, the activation states, the system check, `pricing.toml`.
   Gemini stays the only configured provider until this is proven — adding a
   key is then the whole of turning a second one on.
4. **Tools.** Registry plus suites; the chat assistant switches to the registry
   for its existing three. No new tools yet.
5. **Alerting, before anything can fail silently.** `receive_alerts`
   capability, `AgentHealth`, the themed HTML shell, the state-change alert.
   Ships *ahead* of the fallback removal deliberately: the alarm is wired
   before the thing it watches can break.
6. **Editorial onto the harness.** Six agents lose their clients, parsers and
   fallbacks; personas declared; schemas declared; dedup becomes semantic.
   This is the step that deletes the most code and changes failure behaviour.
7. **Assistant onto the harness.** Persona from shared voice; model from `llm`.
8. **Orchestrator.** Supervisor, registry, dispatch. Until this lands the
   agents are already unified — the orchestrator is the last piece, not the
   first.
9. **New tools for the newsroom** (`fetch_url`, `search_knowledge` for the
   verifier). Separate review; this changes what the agents can do.

Steps 1-5 are additive and safe. Step 6 is the sharp one, and step 5 is what
makes it safe to take.

## Testing

`editorial/llm_fakes.py` (added in `3648418`) already stubs the model across
all six modules and is the foundation. It moves to
`ai_workflows/harness/testing.py` and stubs at the single `llm.get_model` seam
instead of six patch targets — which is itself an argument for the design, as
the fake currently has to know all six module paths.

- Harness units: role→config mapping, fence-strip, schema retry, each error.
- Providers: a key that is absent, present-but-rejected, and valid produce
  `absent`/`candidate`/`active`; resolution honours the preference order and
  skips inactive providers; `allow_fallback = False` raises instead of
  falling over. Every provider HTTP call is stubbed — the suite must not
  reach a vendor, and must not need five API keys to run.
- Catalogue: a refresh that loses a model marks it unavailable rather than
  deleting it; a price keeps its `price_source`; a stale `MANUAL` row is
  reported stale. Fixtures are recorded payloads, not live calls.
- **Fallback removal is asserted:** with the model unavailable, a pipeline run
  must fail and write nothing. Today the equivalent test would assert a canned
  draft exists.
- Memory: `remember` embeds; `recall` returns by similarity, not substring; a
  `BlogPost` edit refreshes its vector.
- Persona: rendered prompt contains the shared brand voice and no
  output-format instruction.
- Tools: an agent is bound its declared suite and nothing else.
- Alerting: a first failure mails the `receive_alerts` holders; a second
  identical failure does not; recovery mails once; a send failure is logged
  rather than swallowed. The suite must never send real mail — Django's
  `locmem` backend is already forced under test in `settings.py`.
- Mail shell: every alert carries both a text and an HTML alternative, the
  HTML has its CSS inlined (no surviving `<style>` block), and the text
  alternative is non-empty. A template that renders only one half is a bug.
- The eighteen editorial tests stay green throughout, unchanged where possible
  — they are the regression net for steps 4-6.

## Out of scope

- Billing anyone from catalogue prices. They are good enough to choose a model
  and to report internal spend, not to invoice from.
- Enabling Codex in production. The seam is built; the default is off, for
  the reasons under Providers.
- Switching the embedding provider. Chat is multi-provider from day one;
  embeddings stay on Gemini for the reason in the risks below.
- Making the eight deterministic services agentic.
- Replacing Celery for agent scheduling.
- Streaming responses.
- Re-tuning any prompt's content. Personas are relocated verbatim; changing
  what they say is a separate, reviewable change.
- Migrating the five existing plain-text transactional emails onto the new
  shell. The shell is built so they can; doing it is its own change.
- Any alert channel that is not email. The limitation is named above, and
  `ApprovalNotification.channel` already anticipates more.

## Open risks

**The reversal is user-visible.** Today a broken key yields a mediocre draft;
after step 6 it yields a failed run. If the newsroom has been quietly running
on fallbacks, this will look like a new outage rather than a newly visible one.
Alerting (step 5) is the mitigation — the failure reaches a person immediately
instead of being discovered later — but it is worth grepping the logs for the
fallback warnings first, to know whether this will be a trickle or a flood on
the day it ships.

**Embedding cost and quota.** Vectorise-on-write adds Gemini embedding calls on
every `BlogPost`/`Project` save. Queued and debounced, but it is new spend
against the same quota the newsroom uses.

**Embeddings still cannot fail over at runtime.** Chat falls between five
providers mid-run without anyone noticing; embeddings cannot, because a vector
from another model is meaningless in the stored space. Changing the model is a
managed migration (see Changing the embedding model) and losing the embedding
provider's key degrades *memory* whatever else is configured. The migration
design removes the cost and the risk of a switch; it does not make embeddings
a runtime fallback, and nothing can.

**The importance score will be wrong at first.** Until `recall()` has
accumulated retrieval counts, the score leans on view counts and recency,
which measure human attention rather than agent usage. The first migration
after this ships will therefore prioritise imperfectly. That is tolerable —
the tail is lazy, so a mis-ranked document is embedded slightly later rather
than never — but the weights should be revisited once real retrieval data
exists rather than being tuned once and forgotten.

**Provider fallback can silently change output quality.** A run that falls
from Claude to DeepSeek on a rate limit produces different prose from the same
prompt. `AgentInvocation` records which model actually served each call, so
this is auditable after the fact, but an editor comparing two drafts will not
be told unless the dashboard surfaces it. Agents whose output is compared
across runs should set `allow_fallback = False`.

**Catalogue prices can be wrong in the direction that matters.** OpenRouter's
margin means a derived price is likely an over-estimate of a direct provider's
rate, and a `MANUAL` row is exactly as current as the day someone last edited
it. Cost reporting built on this is indicative, not accounting. The
`price_source` column exists so that is visible rather than assumed.

**Semantic dedup will behave differently.** Replacing a substring match with
similarity will reject topics the current check waves through, and vice versa.
The threshold needs tuning against real topics, and should be configurable
rather than baked in.

**Stale prompt content.** The assistant's system prompt
(`service.py:88`) still uses the deleted "Test Project" row as its worked
example. Relocating personas verbatim would preserve that. Flagged for the
implementer to fix in passing.
