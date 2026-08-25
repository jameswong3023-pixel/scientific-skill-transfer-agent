# Scientific Skill Transfer Agent

> **Can an agent read a scientific paper, acquire a useful new procedural skill, and then use
> that skill to solve an unseen scientific analysis problem better than the same agent without
> the skill?**

This application makes the answer visible. It extracts an executable *skill* from a methods
paper, then runs **the same agent, twice**, on the same data — once with the skill in its
system prompt, once without — inside the same network-isolated sandbox, and compares the two
runs visually and quantitatively against withheld ground truth.

Everything below was verified against a running stack. Where a number appears, it was
measured, not estimated — including the numbers that do not flatter the result.

**On this dataset, the answer it produced is "no".** Across four A/B trials the
skill-enabled agent never beat the base agent. In the two trials where both arms ran to
completion, the base agent scored **0.997** and **0.980** mean Dice against withheld ground
truth *without* the paper — it solves the task unaided, leaving the skill no headroom — and
in one of those trials the skill arm scored 0.305 because it spent its budget running the
paper's validation checks instead of writing its deliverable. That is a finding about this
benchmark being too easy, not a claim that skill transfer does not work; the full reasoning,
the four trials, and an independent re-verification of the scoring are in
[Example experiment](#example-experiment). The system was built so that it could return this
answer, and it did.

---

## Table of contents

- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Major design decisions](#major-design-decisions)
- [Agent design](#agent-design)
- [LangGraph structure](#langgraph-structure)
- [Experimental fairness](#experimental-fairness)
- [OpenRouter integration](#openrouter-integration)
- [Data model](#data-model)
- [Sandbox implementation](#sandbox-implementation)
- [Progress streaming](#progress-streaming)
- [Imaging and visualisation](#imaging-and-visualisation)
- [Evaluation](#evaluation)
- [Artifacts and export](#artifacts-and-export)
- [Failure handling](#failure-handling)
- [Security boundaries](#security-boundaries)
- [Running the tests](#running-the-tests)
- [Example experiment](#example-experiment)
- [Using a different paper, dataset or modality](#using-a-different-paper-dataset-or-modality)
- [Known limitations](#known-limitations)
- [What I would do with more time](#what-i-would-do-with-more-time)
- [Repository layout](#repository-layout)

---

## Quick start

You need Docker (with Compose v2) and an OpenRouter API key. Nothing else.

```bash
cp .env.example .env            # then set OPENROUTER_API_KEY
docker compose up -d --build    # postgres, redis, minio, sandbox, api, worker, frontend
docker compose run --rm seed --wait
```

Open <http://localhost:3000>.

`seed` is a one-shot compose service (behind the `tools` profile, so `docker compose up`
never starts it). It uploads a sample methods paper, extracts the skill, generates and
uploads the phantom dataset with the correct file roles, launches the A/B experiment, and —
with `--wait` — blocks until both arms are scored and prints the result. Drop `--wait` to
launch and watch it live in the browser instead.

Verify the infrastructure and security claims this README makes:

```bash
bash scripts/verify_stack.sh    # 27 checks; must print "27 passed, 0 failed"
```

<details>
<summary><b>Running the seed script from the host instead of in Docker</b></summary>

The script only speaks HTTP, but it also generates the phantom, so it needs
`httpx`, `numpy`, `scipy`, `nibabel` and `pymupdf`. The backend virtualenv has all five:

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # Windows: .venv/Scripts/pip
cd .. && backend/.venv/bin/python scripts/seed_demo.py --wait
```

Point it elsewhere with `SSTA_API=http://localhost:8200 ... seed_demo.py`.
</details>

<details>
<summary><b>Port 8000 is unavailable on my machine</b></summary>

On Windows, Hyper-V reserves scattered TCP ranges and 8000 is commonly inside one. Docker
reports it as `bind: An attempt was made to access a socket in a way forbidden by its access
permissions`, which looks like a permissions problem but is not — nothing is listening.
Inspect the reservations with:

```
netsh interface ipv4 show excludedportrange protocol=tcp
```

Set `API_PORT=8200` (or anything free) in `.env`. Only the published host port changes;
container-to-container URLs are unaffected, and `scripts/verify_stack.sh` reads `API_PORT`
from `.env` the same way Compose does. The same knob exists for `FRONTEND_PORT`,
`MINIO_PORT` and `MINIO_CONSOLE_PORT`.
</details>

The `Makefile` is a thin convenience wrapper around exactly the commands shown in this
README — `make up`, `make down`, `make reset` (down + volumes), `make logs`, `make demo`,
`make verify`, `make venv`, `make test`, `make lint`, `make test-integration`,
`make test-e2e`. Each recipe's underlying command was run directly during development; the
recipes themselves were not, because `make` is not installed on the machine this was built
on. If a target misbehaves, the command it wraps is one line above it in the file.

---

## Architecture

```
        ┌──────────────┐   HTTP + SSE    ┌───────────────────────────────────┐
        │  Next.js 15  │◀───────────────▶│  api  (FastAPI)                   │
        │  frontend    │   same-origin   │  routers · SSE fan-out · ZIP      │
        └──────────────┘   via rewrite   └────────────────┬──────────────────┘
                                                          │ enqueue (arq over Redis)
                                         ┌────────────────▼──────────────────┐
                                         │  worker  (arq)                    │
                                         │  LangGraph: extraction,           │
                                         │  analysis × 2 arms, evaluation    │
                                         └──┬──────────┬──────────┬──────┬───┘
             ┌──────────────────────────────┘          │          │      │
             │              ┌───────────────────────────┘          │      │
             │              │              ┌───────────────────────┘      │
             ▼              ▼              ▼                              ▼
   ┌───────────────┐  ┌───────────┐  ┌────────────┐   ┌──────────────────────────────┐
   │  postgres     │  │  redis    │  │  minio     │   │  sandbox  (executor API)     │
   │  16 domain    │  │ arq queue │  │ papers/    │   │  network: INTERNAL ONLY      │
   │  tables + 4   │  │ + pub/sub │  │ datasets/  │   │  uid 1000 · rlimits · SIGKILL│
   │  checkpoint   │  │           │  │ runs/      │   │  /work/{run_id}/             │
   └───────────────┘  └───────────┘  └────────────┘   └──────────────────────────────┘
       networks:  core               core + edge                 sandboxnet (no egress)
```

The end-to-end flow the brief describes maps onto it directly:

```
 paper.pdf ──▶ extraction graph ──▶ SkillVersion (JSONB + markdown + provenance)
                                          │
                                          │  system prompt, skill arm only
             ┌────────────────────────────┴───────────────────────────┐
             ▼                                                        ▼
     analysis graph  arm="base"                          analysis graph  arm="skill"
     (no skill in the prompt)                            (skill card appended)
             │                                                        │
             ▼   run_python / write_file / inspect_image / …          ▼
       sandbox /work/{run_id}                                 sandbox /work/{run_id}
             │                                                        │
             └──────────────▶  artifacts (MinIO) + agent_steps  ◀─────┘
                                          │
                              evaluation (deterministic, worker-side,
                              first and only read of ground truth)
                                          │
                                          ▼
                                   comparison UI + ZIP
```

### Services

| Service | Image | Networks | Purpose |
|---|---|---|---|
| `frontend` | `node:20-alpine` → Next standalone | `edge` | UI; proxies `/api/*` to `api` |
| `api` | `backend/Dockerfile` | `edge`, `core`, `sandboxnet` | REST + SSE; runs migrations on boot |
| `worker` | same image as `api`, different command | `core`, `sandboxnet` | arq worker; runs every graph |
| `sandbox` | `sandbox/Dockerfile` | **`sandboxnet` only** | Executes agent-written code |
| `postgres` | `postgres:16-alpine` | `core` | Domain tables + LangGraph checkpoints |
| `redis` | `redis:7-alpine` | `core` | arq queue + event pub/sub |
| `minio` | `minio/minio` | `core`, `edge` | S3-compatible object store |
| `seed` | same image as `api` | `core` | One-shot demo driver (profile `tools`) |

`sandboxnet` is declared `internal: true`, so the sandbox container has **no route to the
internet**. That is the primary isolation guarantee and it is verifiable in one command
rather than asserted in prose (see [Security boundaries](#security-boundaries)).

Three separate networks rather than one: `core` carries credentials (Postgres, Redis, MinIO),
and Postgres and Redis publish no host port at all; `edge` is what the browser can reach;
`sandboxnet` carries no credentials and no egress. `api` is the only service on all three,
and it is the deliberate broker between them.

---

## Major design decisions

| Decision | Reasoning | What it costs |
|---|---|---|
| **Sandbox as a sibling service on an `internal: true` network**, not a Docker socket | Mounting `/var/run/docker.sock` into the API grants host-root equivalence to the process most exposed to user input. The sibling design eliminates that escalation path *and* buys a network guarantee that is provable with `docker network inspect`. | Weaker run-to-run isolation than one container per execution. Workspaces are separated by directory, not by kernel namespace. The production evolution is an ephemeral container per execution. |
| **Skill injected through the system prompt, not as an extra tool** | An arm-specific `get_skill` tool would make the two agents differ in *capability*, not just in *knowledge* — a confound that invalidates the comparison. Tool schemas are the same Python list object for both arms. | The skill must fit in the prompt. With a 1 M-token context window that is not a real constraint. |
| **Structured output exclusively via forced `tool_choice`** | A live probe (2026-08-24) found that `response_format: {type: json_schema, strict: true}` is accepted by `stealth/ox-alpha` with HTTP 200 and then **silently ignored** — it answers in markdown prose. Any code that parses that response crashes at runtime. | One extra schema definition per structured call. `response_format` appears nowhere in the codebase. |
| **Every skill field carries a verbatim quote + page, or is flagged `inferred`** | Without it, "the model read the paper" is unfalsifiable. Quotes are checked by substring containment against the actual extracted page text, so a fabricated quote fails validation and triggers a repair pass. | Extraction is slower and occasionally needs repair rounds. Worth it: it is the difference between provenance and vibes. |
| **Async worker + SSE, never request/response agents** | A skill extraction was measured end to end at 5m28s, and a full two-arm experiment at 14m20s. There is no HTTP timeout that makes a synchronous agent endpoint viable. | Two more moving parts (Redis queue, event stream). |
| **Events persisted to Postgres *then* published to Redis** | SSE subscribes to Redis first, then replays `agent_steps` history from Postgres, de-duplicating on `(run_id, seq)`. A client that connects late, reloads, or reconnects loses nothing — and Redis dying degrades the stream to "history plus keepalives" rather than breaking the run. | One extra INSERT per event. |
| **Server-side PNG slice rendering** | One code path serves NIfTI, DICOM, TIFF, PNG and `.npy`. No JS volume parser, no WebGL, no per-format frontend work. Adding a modality is one `register_adapter()` call. | Latency per slice, and a network round trip per scrub step. Mitigated with `Cache-Control: public, max-age=3600`. |
| **Deterministic metrics only — never an LLM judge** | An LLM-scored comparison of two LLM runs would undermine the exact question the project exists to answer. | No qualitative scoring. A rubric metric could be added later *alongside* Dice, never instead of it. |
| **Hungarian label matching before scoring** | Neither agent is told our label numbering. Calling grey matter `2` when we call it `1` is not a segmentation error and must not score zero. | Background is pinned to itself rather than matched — see [Evaluation](#evaluation) for the bug that forced this. |
| **The phantom generator is committed, not the phantom** | `.gitignore` excludes `*.nii.gz` so large binaries stay out of git. Generation is deterministic for a given seed, so every reviewer gets an identical phantom without the repo carrying volumes. | One extra step on first run, handled automatically by the seed script. |
| **`skill_versions` is append-only, and an experiment pins one** | Re-extracting a skill creates version N+1 and leaves prior experiments reproducible against exactly the skill text they ran with. | None worth mentioning. |

---

## Agent design

Three agents, all going through the same OpenRouter client.

### 1. Skill extraction — `backend/app/agents/skill_extraction/`

The paper is not treated as retrieval context. It is parsed into per-page text with page
markers (`[PAGE 7] …`), and the model is asked to emit a structured, executable
specification through a forced function call.

- **`segment_methods`** — for papers longer than 6 pages, builds a 300-character index per
  page and asks the model which pages carry the methodology, keeping the answer only if at
  least two pages match. Anything else falls back to all pages. With a 1 M-token context
  window this is an optimisation, not a necessity, which is why the fallback is generous.
- **`extract_skill`** — one forced `emit_skill` tool call. The schema is in
  `schema.py`: `name`, `description`, `intended_task`, `modality`, `input_requirements`,
  `output_specification`, `preprocessing_steps`, `algorithm_steps`, `equations`,
  `initialization`, `parameters`, `stopping_criteria`, `postprocessing`,
  `required_dependencies`, `validation_checks`, `known_failure_modes`, `citations`. Every
  `AlgorithmStep` and `Parameter` carries either `provenance {quote, page}` **or**
  `inferred: true`.
- **`validate_skill`** — deterministic, no model involved. It checks: at least 3 algorithm
  steps; step `order` values form `1..N` with no gaps or duplicates; every non-inferred
  field's quote actually appears on a page; the fraction of inferred content is not
  absurd; dependencies are named; and a stopping criterion exists if any step mentions
  iteration. Quote matching normalises both sides first (NFKC, ligature expansion,
  de-hyphenation across line breaks, curly-quote folding, whitespace collapse, lowercase)
  because PDF text extraction inserts hard line breaks mid-word and a model quoting the
  paper silently repairs them — matching raw strings would flag honest quotes as
  hallucinations. Quotes under 12 normalised characters are rejected outright as too short
  to be evidence.
- **`repair`** — feeds the validation report back as a corrective turn and forces the tool
  call again. At most 2 repairs, so at most 3 extraction attempts. Warnings never trigger a
  repair; only errors do.
- **`finalize`** — renders the markdown skill card that the skill arm actually receives.

The skill and its validation report are persisted as an immutable `SkillVersion` row.
The UI renders the card with a green `p.N` chip beside every quoted field, which opens the
verbatim quote and deep-links to the rendered PDF page image, and an amber `inferred` chip
where the model supplied something the paper did not say.

### 2. Analysis — `backend/app/agents/analysis/`

A tool-using loop over the sandbox. Both arms run this graph.

Tools (identical for both arms, in `agents/tools/sandbox_tools.py`):

| Tool | What it does |
|---|---|
| `list_files` | Lists the run workspace with sizes. |
| `inspect_image` | Shape, dtype, voxel spacing, intensity range, percentiles, and whether the data looks like a label map — without the agent writing loader code. Works for NIfTI, DICOM, TIFF, PNG/JPEG, `.npy`. |
| `read_text` | Reads a text file back (its own script, a log). |
| `write_file` | Writes a text file without executing it. |
| `run_python` | Writes a script into the workspace and runs it. Returns exit code, stdout, stderr and files created. |
| `list_packages` | The installed package list. There is no network and no installer, so this is how the agent discovers what it has. |
| `save_artifact` | Marks a produced file as a deliverable, with a `kind` of `output`/`figure`/`report`/`code`/`log`. |

`dispatch_tool` **never raises**. An unknown tool name returns a message listing the real
tools and noting there is no package installer; a missing argument returns a description of
what was missing; any other exception returns `Tool 'x' raised an error: …`. An exception
would end the run; a described error lets the agent adapt, which is the whole point.

The shared system preamble tells both arms: the sandbox is isolated, there is no network and
no `pip install`, inspect before assuming, print diagnostics and read them, fix the specific
cause rather than rewriting from scratch, and verify numerically — *"a segmentation that
assigns every voxel to one class is a failure even if the script exits 0."*

### 3. Conversation — `backend/app/agents/conversation/`

A bounded ReAct-style tool loop (5 rounds, then a forced tool-free answer) over six
**read-only** tools: `get_experiment_summary`, `get_skill`, `list_artifacts`,
`read_artifact_text`, `get_run_steps` (with a `only_failures` filter), `get_metrics`. It
deliberately cannot execute code or write files — it reads exactly the rows the UI renders.

It is grounded by instruction *and* by construction: it is told to look a value up before
quoting it, to read the actual run steps when asked why something failed, and to check the
skill's provenance when asked where a parameter came from. Because the tools return real
`agent_steps` and `metrics` rows, "Why did the first segmentation fail?" is answered from
the recorded stderr, not from imagination. Every failure path in the loop degrades to prose
("I ran out of lookups before I could answer") rather than raising.

> This one is a plain async loop, not a `StateGraph`, even though it lives in a file called
> `graph.py`. It has no branching worth modelling and no state worth checkpointing; adding a
> graph would have been ceremony. LangGraph is used where it earns its place.

---

## LangGraph structure

### Extraction graph

```
START → segment_methods → extract_skill → validate_skill ──┬─(ok / budget spent)─→ finalize → END
                                ▲                          │
                                └────────── repair ◀───────┘  (errors, ≤ 2 passes)
```

- Conditional edge: `route_after_validation` → `{"repair", "finalize"}`. Precedence: a hard
  error finalises; `validation.ok` finalises; `repair_count >= 2` finalises; otherwise repair.
- State: `pages`, `title`, `skill`, `validation`, `repair_count`, `usage`, `error`,
  `_repair_prompt`. Note the leading underscore key is *declared* in the `TypedDict` —
  LangGraph silently drops keys a node returns that the state does not declare, and losing
  the repair prompt made the repair loop a no-op that looked like it worked.
- `recursion_limit = 25`.

### Analysis graph

```
START → plan → agent_step ──┬── tools ──┐
                            │           │  (loops back)
                            │◀──────────┘
                            └── summarize → END
```

- Conditional edge: `route` → `{"tools", "summarize"}`. Precedence: `error` set → summarize;
  `iterations >= max_iterations` → summarize; pending tool calls → tools; else summarize.
- State: `run_id`, `arm`, `task`, `manifest_block`, `skill`, `messages`, `iterations`,
  `max_iterations`, `usage`, `summary`, `error`, `last_failed`, `_pending_calls`.
- **Retries / recovery**: there is no separate repair node. After a `tools` visit, if any
  `run_python` observation came back `FAILED`, one corrective user turn is appended telling
  the model to diagnose from the traceback, change only what is broken, not restart from
  scratch, and not re-run identical code. Control then flows back to `agent_step` on the
  ordinary edge, so recovery is a normal iteration and shows up as one in the metrics.
- **Budget**: `AGENT_MAX_ITERATIONS`, default 16, counted per `tools` visit.
  `recursion_limit = budget * 3 + 12`. When the budget is spent, `summarize` appends a
  "you have reached your step budget" turn and makes one final tool-free call, so a run
  always ends with a written summary rather than a truncation.
- **Branching**: the arm never appears in the control flow. See below.

### Persistent run state and checkpointing

`AsyncPostgresSaver` from `langgraph-checkpoint-postgres`, with **`thread_id = run.id`**.
The same value is denormalised onto `runs.thread_id` (indexed), so persisted graph state
joins directly back to the domain record.

The checkpointer is attached **best effort**: both the import and the connect/`setup()` are
wrapped, and either failure logs a warning and yields `None`, which compiles the graph with
plain in-memory state. The experiment is the product; losing resumability is far cheaper
than losing the run. Unit tests pin both degradation paths.

This creates four tables — `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`,
`checkpoint_migrations` — in the same database as the 16 domain tables, but outside Alembic's
control, because the library owns their schema.

**How LangGraph state and database state interact.** LangGraph owns *in-flight* state, keyed
by `thread_id`, and gives crash-resume for free. The domain tables own the *durable,
queryable* record: `agent_steps` (what happened, in order), `tool_calls`, `artifacts`,
`metrics`. Node transitions write to both — the checkpoint automatically, `agent_steps`
explicitly through the event emitter. They reconcile on `run.thread_id`. That split is
deliberate: LangGraph checkpoints are an implementation detail of the framework and are not
something a UI, a metric, or a reviewer should have to parse.

---

## Experimental fairness

Both arms receive an identical: model, temperature, `max_tokens`, tool schema list,
iteration budget, sandbox image, staged dataset, and task text. They run **the same graph
object**. The *only* difference is the string returned by
`build_system_prompt(arm, skill)` in `backend/app/agents/analysis/prompts.py`.

- `base` returns the shared preamble verbatim, and **raises `ValueError` if a skill is
  passed** — "the base arm must never receive a skill" is enforced, not remembered.
- `skill` returns the shared preamble plus a `## Available technique` header plus the
  rendered skill card.

`backend/tests/unit/test_experimental_fairness.py` fails the build if that stops being true.
It asserts the two prompts share a byte-identical prefix and that the remainder is only the
skill block; that both arms get the same `TOOL_SCHEMAS` object; that sampling parameters
match; and — a source-level check — that the strings `arm == "skill"`, `arm == 'skill'` and
`arm != "base"` do not appear anywhere in the analysis graph module, so no one can quietly
reintroduce an arm-conditional branch.

Ground truth is withheld structurally: `dataset_files.role == 'ground_truth'` files live
under their own object-storage prefix and are excluded by an **allowlist**
(`STAGEABLE_ROLES = {input, aux}`) in `stage_dataset()`, which is the single function
through which any dataset byte reaches a sandbox. Ground truth is read exactly once, in the
worker, after both runs have finished.

> **Determinism caveat, stated plainly.** OpenRouter accepts a `seed` for this model but
> offers no reproducibility guarantee, and `temperature=0` is not one either. Repeated runs
> will vary. A single A/B pair is **one sample, not a proof**. The honest version of this
> experiment is N trials with confidence intervals; see
> [What I would do with more time](#what-i-would-do-with-more-time).

---

## OpenRouter integration

`backend/app/agents/llm.py`. OpenRouter is the only gateway; there is no provider SDK
anywhere in the tree.

- **Endpoint** `{OPENROUTER_BASE_URL}/chat/completions`, default base
  `https://openrouter.ai/api/v1`. Model default `stealth/ox-alpha`, override with
  `OPENROUTER_MODEL`.
- **Headers**: `Authorization: Bearer …`, `Content-Type: application/json`,
  `HTTP-Referer: {OPENROUTER_APP_URL}`, `X-Title: {OPENROUTER_APP_TITLE}` — the last two are
  OpenRouter's app-attribution headers.
- **Three entry points**: `chat()` (tools optional), `structured()` (forced function call,
  returns parsed arguments plus usage), `stream()` (SSE token deltas; no tools).
- **Structured output**: `structured()` wraps the JSON schema as a function tool and forces
  it with `tool_choice: {type: function, function: {name}}`, then parses
  `tool_calls[0].function.arguments`. This is the direct consequence of the
  `response_format` finding above.
- **Retries — three independent budgets, distinguished in the logs so a rate limit is never
  confused with a model formatting failure:**
  1. *Rate limit*: up to 5 extra attempts on HTTP 429 with exponential backoff
     2 s → 4 s → 8 s → 16 s, capped at 30 s. The upstream model genuinely returns 429s under
     load, so this path is exercised in practice.
  2. *Transport*: up to 3 attempts on `httpx.TransportError` and retryable statuses
     (`408, 409, 425, 500, 502, 503, 504`) with 1 s → 2 s backoff. Any other 4xx raises
     `PermanentOpenRouterError` immediately rather than burning the budget on something that
     will never succeed.
  3. *Structured output*: up to 3 model calls when the model answers with prose instead of
     calling the forced tool, or emits `arguments` that are not valid JSON. Each retry
     appends the offending reply plus a corrective turn.

  An HTTP 200 whose body carries an `error` object — OpenRouter does this for body-level
  throttling — is re-classified through the same path, so a throttle is never mistaken for
  a successful empty response.
- **Timeouts**: 900 s for `chat` and `stream`, applied to connect/read/write/pool alike.
  Individual calls against this model routinely run for minutes; a complete skill extraction,
  which is several calls plus a validation loop, was measured at 5m28s.
- **Usage accounting**: a `Usage` dataclass (`prompt_tokens`, `completion_tokens`,
  `total_tokens`, `cost`) with `__add__`, summed across retries inside `structured()` and
  merged into graph state per call. It lands in `runs.totals` and in `metrics` rows scoped
  `system`. This model currently reports **cost 0**, so that column reads zero — the
  accounting is wired, the price is not.
- **Private reasoning is actively scrubbed.** A live probe confirmed this model *does*
  populate `message.reasoning` on ordinary tool-call responses. `_scrub_reasoning()` strips
  `reasoning`, `reasoning_details` and `reasoning_content` from the top level of the body
  and from every `choices[i].message` and `choices[i].delta` before the raw body is attached
  to the response object. `LLMResponse` has no `reasoning` attribute at all, and the
  frontend's TypeScript event type has no such field. The brief forbids surfacing raw
  reasoning; this removes it at the boundary rather than relying on nobody reading it.

---

## Data model

Postgres, 16 domain tables. Large binaries **never** live in rows — only `storage_key`
pointers into MinIO. Every table inherits a UUID `id` (generated client-side, so a service
can derive an object-storage key before the INSERT lands) and a timezone-aware `created_at`.

```
users(id, email✦, created_at)
workspaces(id, user_id→users⌫, name, created_at)

papers(id, workspace_id→workspaces⌫, title, filename, storage_key, sha256⊙,
       page_count, status, error, created_at)
       status: uploaded → parsing → parsed → extracting → extracted | failed
paper_pages(id, paper_id→papers⌫, page_number, text, char_count, image_storage_key)
       unique(paper_id, page_number)

skills(id, workspace_id⌫, paper_id→papers∅, name, slug⊙)
skill_versions(id, skill_id→skills⌫, version, payload⬢, markdown, model,
               extraction_run_id, validation⬢)
       unique(skill_id, version) — append-only

datasets(id, workspace_id⌫, name, modality, description)
dataset_files(id, dataset_id→datasets⌫, role⊙, filename, storage_key, sha256,
              bytes, media_type, file_metadata⬢)
       role: 'input' | 'ground_truth' | 'aux'

experiments(id, workspace_id⌫, paper_id∅, skill_version_id∅, dataset_id∅,
            task_prompt, status⊙, config⬢, completed_at)
runs(id, experiment_id→experiments⌫, arm, status⊙, thread_id⊙, workspace_dir,
     started_at, finished_at, error, totals⬢)
       unique(experiment_id, arm) — exactly one run per arm

agent_steps(id, run_id→runs⌫, seq, node, kind, title, detail, payload⬢)
       unique(run_id, seq) — this is what makes SSE de-duplication sound
tool_calls(id, run_id⌫, step_id→agent_steps∅, tool_name⊙, args⬢, result⬢,
           status, duration_ms)
artifacts(id, run_id⌫, kind⊙, path, storage_key, media_type, bytes, sha256,
          artifact_metadata⬢)
metrics(id, experiment_id⌫, run_id⌫ NULL, scope, key⊙, value_num, value_json⬢)
       scope: 'quality' | 'system' | 'comparison'

conversations(id, workspace_id⌫, experiment_id⌫, title)
messages(id, conversation_id→conversations⌫, role, content, tool_calls⬢)

⌫ ON DELETE CASCADE   ∅ ON DELETE SET NULL   ⊙ indexed   ✦ unique   ⬢ JSONB
```

Plus `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations` owned by
LangGraph.

Judgement calls worth naming:

- **Versioning.** `skill_versions` is append-only and an `experiment` pins an exact
  `skill_version_id`. Re-extracting a paper produces version N+1 and does not disturb any
  experiment that already ran.
- **Ownership vs reference.** Deletes cascade along ownership edges (a paper owns its pages,
  a run owns its steps) and null out along soft references (`experiments.paper_id`), so
  deleting a paper does not destroy the experimental record that cites it.
- **Object-storage key layout** encodes the trust boundary:
  `datasets/{dataset_id}/{role}/{filename}` puts ground truth under its own prefix, so a
  prefix listing of agent-visible inputs cannot reach it. Agent-controlled paths
  (`runs/{run_id}/{path}`) go through a `_safe_relpath()` guard that rejects absolute paths
  and any `..` component, because agent-generated code names its own output files.
- **`sha256` is stored on every uploaded and produced object**, which is what makes an
  experiment auditable after the fact.
- **Migrations.** One migration, `0001_initial`, creating all 16 tables with their indexes,
  cascade rules and named unique constraints. The `api` container runs
  `alembic upgrade head` before `uvicorn` on every start, so a cold
  `docker compose up` provisions the schema with no manual step. Verified against a
  genuinely empty database (a throwaway `ssta_coldcheck`): `upgrade head` produced exactly
  the 16 domain tables plus `alembic_version`, and `downgrade base` removed all 16 again.
  See [Known limitations](#known-limitations) for how the file was authored and what guards
  it against drifting from the models.

---

## Sandbox implementation

`sandbox/` is a separate image and a separate service. Agent-generated code is never
`exec`'d in the API or the worker.

- **Image**: `python:3.11-slim` plus `libglib2.0-0`, `libgl1`, `libgomp1` for headless
  OpenCV. Pre-baked, exact-pinned: numpy 2.2.1, scipy 1.15.0, scikit-image 0.25.0,
  scikit-learn 1.6.0, opencv-python-headless 4.10.0.84, nibabel 5.3.2, SimpleITK 2.4.1,
  pydicom 3.0.1, tifffile 2025.1.10, imagecodecs 2024.12.30, pandas 2.2.3,
  matplotlib 3.10.0, Pillow 11.1.0. `MPLBACKEND=Agg` is baked in so a plotting call cannot
  block on a missing display.
- **Identity**: `USER 1000:1000`, re-asserted in compose. Never root.
- **Network**: attached only to `sandboxnet` (`internal: true`). No egress, therefore no
  `pip install` — which is why `list_packages` exists as a tool and why the system prompt
  states the constraint up front.
- **Environment**: deliberately only `SANDBOX_WORK_ROOT`, `SANDBOX_MAX_TIMEOUT_S`,
  `SANDBOX_MEMORY_MB`. No API key, no database URL, no S3 credentials. The child process
  gets a *freshly built* environment (`PATH`, `HOME=/tmp`, matplotlib backend, thread caps)
  and inherits nothing from the server process.
- **HTTP surface**: `GET /healthz`, `GET /packages`, `POST /exec`, `POST /write`,
  `GET /files`, `GET /file`, `POST /reset`. Nothing else, and no host port published.
- **Resource limits** (POSIX, applied in a `preexec_fn`): `RLIMIT_AS` = `SANDBOX_MEMORY_MB`
  (default 3072 MB), `RLIMIT_CPU` = the request's wall-clock budget with a 5 s hard grace,
  `RLIMIT_NOFILE` = 1024, `RLIMIT_NPROC` = 256, `RLIMIT_CORE` = 0, then `os.setsid()`.
- **Wall clock**: `timeout_s` is clamped to `[1, SANDBOX_MAX_TIMEOUT_S]` (900 s ceiling) and
  enforced by `subprocess.run(timeout=…)`, which SIGKILLs the child. On expiry the result is
  `exit_code=124`, `timed_out=true`, partial stdout/stderr preserved and a
  `[sandbox] killed after Ns wall-clock limit` line appended to stderr. It comes back as an
  ordinary observation the agent can read and react to — never an exception.
- **Path containment**: `workspace_path()` sanitises the run id to alphanumerics plus `-_`;
  `resolve_in_workspace()` rejects absolute paths, `~`, and drive letters, then resolves and
  asserts the result is under `/work/{run_id}`. Every file-touching endpoint goes through it
  and returns HTTP 400 on violation.
- **Output capture**: stdout and stderr are each truncated at 200 000 characters, keeping
  the head and tail with an explicit `...[N chars truncated]...` marker in the middle — a
  traceback is usually at the end, and a shape printout at the beginning.
- **Client contract**: `SandboxClient.execute()` **never raises**. A transport failure or a
  non-2xx becomes `ExecutionResult(exit_code=-1, stderr="Sandbox unavailable: …")`, because
  the agent must always receive an observation it can reason about. Its HTTP timeout is
  deliberately `sandbox_timeout_s + 60` so the client observes the sandbox's verdict rather
  than inventing its own.

Verified live, all of it, by `scripts/verify_stack.sh` and
`backend/tests/integration/test_resilience.py`.

---

## Progress streaming

Long-running work reaches the browser over SSE.

- The worker's emitter **persists an `agent_steps` row and commits, then publishes** to
  Redis `run:{run_id}:events` and `experiment:{experiment_id}:events`. A publish failure logs
  a warning; a dead Redis must never fail an analysis.
- `GET /api/experiments/{id}/events` **subscribes first, then replays.** It attaches to
  Redis (waiting up to 5 s for the subscription to land), buffers live frames in a queue,
  then reads history from Postgres and emits it while recording `(run_id, seq)` keys,
  dropping any live frame already covered. Subscribe-then-replay rather than
  replay-then-subscribe closes the gap where an event published *during* the history read
  would otherwise be lost by both paths.
- Event shape:
  ```json
  {"run_id":"…","arm":"skill","seq":12,"kind":"tool_call","node":"execute_code",
   "title":"Running segmentation.py","detail":"exit=1 shape mismatch","ts":"…"}
  ```
- A 15-second keepalive comment goes out on every idle tick, and the stream closes with a
  terminal `event: end` frame once the run or experiment reaches a terminal status. Fifteen
  seconds is short relative to the multi-minute silences a single model call produces — long
  quiet stretches are normal here, and the client must not conclude the stream is dead.
- Headers: `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`.
  Payload newlines are escaped so a multi-line detail cannot split an SSE frame.
- The frontend uses a plain `EventSource` (same-origin thanks to the Next rewrite, so no
  CORS and no polyfill), keeps its own `(run_id, seq)` de-duplication set, and lets
  `EventSource` auto-reconnect — safe precisely because the server replays.

---

## Imaging and visualisation

`app/imaging/loaders.py` normalises every format to `(numpy array, metadata)` behind a
one-line adapter registration:

| Adapter | Extensions | Library |
|---|---|---|
| NIfTI / MGH | `.nii`, `.nii.gz`, `.mgz`, `.mgh` | nibabel |
| TIFF | `.tif`, `.tiff`, `.ome.tif`, `.ome.tiff` | tifffile |
| DICOM | `.dcm`, `.dicom`, `.ima` | pydicom |
| Bitmap | `.png`, `.jpg`, `.jpeg`, `.bmp`, `.gif`, `.webp` | Pillow |
| Raw array | `.npy` | numpy |

Anything unregistered, or any adapter that throws, raises a typed `UnreadableImageError`,
which the upload probe records in `dataset_files.file_metadata` and the agent's
`inspect_image` tool surfaces as a normal observation.

Rendering is server-side. `GET /api/artifacts/{id}/slice?axis=axial&index=72&cmap=gray`
returns a PNG plus an `X-Slice-Count` header, so the client learns the volume's depth from a
response header and never parses a volume. (The client currently asks for that header with a
`HEAD` request, which does not work — see [Known limitations](#known-limitations).) Masks
render as a **separate transparent
RGBA PNG** through `/overlay?alpha=…`, using a 13-entry colour-blind-safe palette with label
0 reserved as fully transparent. The UI stacks base and overlay as two absolutely positioned
images, with axis tabs (axial / coronal / sagittal), a range scrubber, arrow-key navigation,
an overlay toggle and an alpha slider.

---

## Evaluation

`app/evaluation/metrics.py`. Deterministic, never a model.

**Quality metrics**, per class and averaged: Dice, IoU, precision, recall, and volume error
(predicted mm³, true mm³, absolute error, percentage error, using the ground-truth voxel
spacing).

**Label permutation** is handled by building the full prediction × truth overlap matrix and
solving it with the Hungarian algorithm (`scipy.optimize.linear_sum_assignment` on the
negated overlap). Neither agent is told our numbering, so a correct segmentation that calls
white matter `1` instead of `3` must not score zero.

> Background is **pinned to itself** rather than included in the assignment. Matching every
> label including background let a degenerate all-background prediction be rescued by
> relabelling background as a foreground class: `np.zeros(...)` against `[0,1,1,2]` scored
> 0.33 instead of 0.0. Background is the one label both sides genuinely agree on, so it is
> excluded from the permutation search.

A shape mismatch short-circuits to a structured `{"error": "shape_mismatch", "detail": …}`
result rather than an exception, so a run that produced a wrongly shaped volume still gets a
comparison page explaining why it scored zero.

**Which artifact gets scored.** A run may write several volumes. Candidates are ranked by
name (`segmentation` > `segment` > `labels` > `label` > `mask` > `classes` > `tissue`) with
anything matching bias / field / preview / overlay / histogram / input / corrected rejected
outright, and then each candidate is actually decoded and scored in order until one succeeds
— so a run that wrote both `bias_field.nii.gz` and `segmentation.nii.gz` is scored on the
segmentation, and a run whose top-ranked file fails to decode falls through to the next
rather than reporting zero. This is why the seeded task prompt names `segmentation.nii.gz`
explicitly.

**System metrics**, per arm: `agent_steps`, `code_executions`, `failed_executions`,
`runtime_seconds`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost`.

**Ground-truth isolation.** Evaluation is the *first and only* read of a `ground_truth`
file, it happens in the worker after both runs are finished, and if the dataset has no
ground truth it returns `{"evaluated": false, "reason": "no ground truth in dataset"}` and
the experiment still completes with system metrics. Evaluation being unavailable must never
be the same thing as the run failing.

---

## Artifacts and export

Every file the agent registers with `save_artifact` is uploaded to MinIO under
`runs/{run_id}/{path}` and recorded in `artifacts` with kind, media type, size and sha256.
`GET /api/experiments/{id}/download` streams a ZIP:

```
experiment.json                       # id, task, status, config
skill/skill.json                      # the exact SkillVersion payload that ran
skill/skill.md                        # the rendered card the skill arm received
base_agent/run.json                   # status + totals
base_agent/generated_code/…           # every artifact of kind code|log
base_agent/outputs/…                  # every artifact of kind output|figure|report
skill_agent/run.json
skill_agent/generated_code/…
skill_agent/outputs/…
comparison/metrics.json               # {by_arm: {base: …, skill: …}, comparison: …}
```

The ZIP is streamed in 8 MB chunks through a write-only, non-seekable sink, which makes
`zipfile` emit data descriptors — the documented way to stream an archive. (Rewinding a
shared `BytesIO` between flushes corrupted every member header offset after the first.)
A missing or unreadable object is logged and skipped so one bad artifact does not cost the
whole download.

---

## Failure handling

Every row below is exercised by a test; the sandbox rows are exercised against the real
sandbox in `backend/tests/integration/test_resilience.py` (17 tests, all passing).

| Failure | Response |
|---|---|
| PDF has the wrong extension, wrong magic bytes, is empty, or is too large | Rejected at upload with HTTP 400 and a specific reason, before anything is parsed |
| PDF parses but is a scan | Per-page raster PNGs are stored; the model's vision input is the fallback path |
| PDF parsing throws | Paper status `failed` with the error recorded and shown in the UI |
| Model answers with prose instead of the forced tool call | Retried up to 3 times with a corrective turn; then `StructuredOutputError` |
| Model emits invalid JSON arguments | Same structured-output retry loop |
| Extracted skill fails validation | Repair loop, ≤ 2 passes, feeding the exact validation errors back |
| Model quotes a sentence that is not in the paper | Counted as an unverified quote, raised as a validation error, drives a repair pass |
| Generated code fails | Non-zero exit returns as a normal observation with stderr; a repair instruction is appended and the loop continues |
| Generated code never terminates | SIGKILL at the wall-clock limit, `timed_out: true`, `exit_code: 124` — returned as an observation |
| Generated code exhausts memory | `RLIMIT_AS` trips, the process dies, non-zero exit returned as an observation |
| Generated code tries the network or `pip install` | Fails with `OSError`; the prompt states the constraint and `list_packages` shows what is available |
| Generated code tries to escape the workspace | `PathEscapeError` → HTTP 400 from the executor |
| Sandbox service is unreachable | `execute()` returns `exit_code=-1, stderr="Sandbox unavailable: …"`; the agent sees an observation, not a crash |
| Malformed or unreadable image | Upload succeeds, `UnreadableImageError` is recorded in `file_metadata`; the agent's `inspect_image` reports it and continues |
| Prediction has the wrong shape | Structured `shape_mismatch` result, mean Dice 0, comparison page still renders |
| Dataset has no ground truth | Evaluation skipped with a reason; the run still completes |
| Redis is down | Events still persist to Postgres; SSE degrades to history plus keepalives |
| Object store is slow at boot | Startup bucket check is capped at 5 s and degrades to a warning |
| One arm crashes | It is marked `failed` with the error; the other arm still renders and is still scored |
| Run crashes mid-way | LangGraph checkpoint under `thread_id = run.id` survives it; the arq job retries once |
| Model rate-limits (429) | Five backed-off retries, 2 → 16 s, logged distinctly from transport errors |

---

## Security boundaries

Every claim here is checked by `scripts/verify_stack.sh` against the running stack
(27 checks, currently 27/27) and, where it needs code, by the resilience suite.

1. **The sandbox has no internet.** `sandboxnet` is `internal: true` and the sandbox is
   attached to nothing else. Probes to `1.1.1.1:53`, `8.8.8.8:53` and `openrouter.ai:443`
   all fail with `OSError`.
2. **The sandbox holds no secrets.** `OPENROUTER_API_KEY`, `DATABASE_URL`, `S3_SECRET_KEY`
   and `REDIS_URL` are all absent from its environment — verified by asserting `printenv`
   fails for each — while `api` and `worker` do have the key. Agent code that reads
   `os.environ['OPENROUTER_API_KEY']` raises `KeyError`.
3. **The sandbox is unprivileged**: uid 1000, not root, no published host port, `tmpfs`
   `/tmp`.
4. **Resource limits**: `RLIMIT_AS`, `RLIMIT_CPU`, `RLIMIT_NPROC`, `RLIMIT_NOFILE`,
   `RLIMIT_CORE`, plus a wall-clock SIGKILL.
5. **Path containment**: every sandbox path is resolved and asserted under `/work/{run_id}`.
6. **Upload validation**: extension allowlist plus magic-byte sniff for PDFs, size caps
   (60 MB papers, 500 MB dataset files), filename traversal rejection, and content hashes on
   everything stored.
7. **Object-key hygiene**: agent-chosen output paths are normalised and rejected if they
   contain `..`.
8. **Agent-generated code is never `exec`'d by the API or worker.** It is treated as hostile
   input and only ever crosses the HTTP boundary into the sandbox.
9. **Ground truth is withheld by an allowlist in a single chokepoint**, `stage_dataset()`,
   and read only by the evaluator after both runs finish.
10. **Private model reasoning is scrubbed at the client boundary**, not merely unused — this
    model does return it.
11. **CORS is an explicit allowlist** (`http://localhost:3000`, `http://frontend:3000`), not
    `*` — and in normal operation the browser never needs it, because the Next.js rewrite
    makes every API call same-origin.

---

## Running the tests

```bash
# Unit tests: 279 passing, no services needed. Uses the backend virtualenv.
cd backend
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # POSIX: .venv/bin/pip
.venv/Scripts/python -m pytest tests/unit -q
.venv/Scripts/python -m ruff check .

# Integration + resilience: 21 passed, 6 skipped in ~44s. Runs inside the api container,
# because the sandbox containment tests must reach sandboxnet, which is internal.
docker compose exec -T -e RUN_INTEGRATION=1 api python -m pytest tests/integration -v

# Infrastructure and security posture, against the live stack: 27 passed, 0 failed.
bash scripts/verify_stack.sh

# The full A/B experiment against the real model, extraction included: 15-25 minutes.
cd backend && RUN_E2E=1 python -m pytest tests/integration/test_full_experiment.py -v -s
```

`make test`, `make lint`, `make test-integration`, `make test-e2e` and `make verify` wrap
those; `make venv` does the one-time virtualenv setup.

The six skips in the integration run are deliberate and each says why: the four
`test_full_experiment` tests need `RUN_E2E=1` (extraction plus a full experiment, 15–25
 minutes), and the two
`test_real_extraction` tests need both an `OPENROUTER_API_KEY` in the environment and
`fixtures/sample_methods_paper.pdf`, which is not copied into the backend image. Run those
two from a host checkout with the key exported — they pass, in 8m27s, and they are the
strictest check in the repository: one of them asserts
`validation["unverified_quotes"] == 0`, i.e. that the model fabricated no quotes at all. Similarly, two unit-test modules
(`test_phantom.py`, `test_brainweb_decode.py`) cover `scripts/` and skip themselves inside
the container for the same reason.

What the suite actually pins, beyond the obvious:

- **Experimental fairness** — identical tool schemas and sampling parameters, a byte-identical
  system-prompt prefix, and a source-level check that the analysis graph contains no
  arm-conditional branch.
- **Ground-truth isolation** — a dedicated leak test on `stage_dataset()`.
- **Compose posture** — `sandboxnet` is internal, the sandbox is attached to nothing else,
  publishes no host port, receives no secrets, and runs as uid 1000. Parsing the compose file
  makes those regressions fail at edit time rather than at deploy time.
- **Migration drift** — the initial migration is AST-parsed and diffed against the SQLAlchemy
  models.
- **Hostile code containment** — infinite loops, busy spins, memory bombs, `/etc/shadow`
  reads, network egress, reaching `openrouter.ai`, reading the API key out of the
  environment, writing outside the workspace, and `pip install`. All seven hostile programs
  are actually submitted to the real sandbox and all come back as contained failures with the
  API still healthy.
- **Phantom difficulty** — a test asserts that bias-corrected clustering beats bias-blind
  clustering on the generated phantom by a real margin. If it stopped being true, the A/B
  comparison would be measuring nothing, and the build should fail.
- **Phantom determinism and resolution independence** — the same seed must produce the same
  volumes, and the bias field's shape must not change with `--size`.
- **The slice HEAD contract** — `test_slice_head_probe.py` asserts the slice routes accept the
  HEAD probe the viewer actually sends. It began life as a strict `xfail` pinning the defect
  described below, and turned into a failing test the moment the routes were fixed, which is
  what forced it to become a real assertion rather than a memorial to a solved bug.

And, honestly, what the suite does **not** pin: nothing exercises the browser's own request
methods, which is why the slice-navigation defect above survived a green suite and was only
found by probing the live API by hand.

---

## Example experiment

Produced on 2026-08-25 against `stealth/ox-alpha` through OpenRouter. Four trials were run:
two at the original 8-iteration budget, and two more after that budget was diagnosed as too
small and raised to 16. Every number below is copied from a real run; nothing here is
illustrative, and nothing has been selected for looking good. The two 8-iteration trials are
kept exactly as they were run rather than quietly replaced, because *why* they had to be
rerun is itself part of the result.

> **The honest headline first.** Across four trials the skill-enabled arm never beat the
> base arm on segmentation quality. At 8 iterations neither arm could reliably finish, so
> those trials measured truncation rather than skill transfer. At 16 iterations both arms
> could finish — and the base agent scored **0.997** and **0.980** mean Dice, essentially
> solving the task unaided, against the skill arm's 0.995 and 0.305. **The honest reading is
> that this benchmark saturates.** A frontier model given enough steps builds a competent
> segmentation pipeline on its own, which leaves the skill no headroom to demonstrate value;
> and in the fourth trial the skill's own instruction to run the paper's validation checks
> consumed the budget that shipping the deliverable needed. On this evidence **the answer to
> the core question is "no measurable benefit, and one measurable harm"** — reported as
> found. Details and all four trials below.

### 1. Paper → skill

Input: `fixtures/sample_methods_paper.pdf`, 4 pages — a synthetic stand-in for Ahmed et al.
that paraphrases bias-corrected, neighbourhood-regularised fuzzy c-means in text this
project owns (the real paper is IEEE-copyrighted and is not committed).

```
extracted 'BCFCM' in 5m28s -- 8 steps, 8 parameters, 16 verified quotes, 0 unverified
validation: {"ok": true, "issues": [], "inferred_ratio": 0.188,
             "verified_quotes": 16, "unverified_quotes": 0}
```

Every one of the 16 quotes was checked by substring containment against the actual
extracted page text. Zero were fabricated. The parameters it pulled out, with the page each
came from:

| Symbol | Value | Source | Meaning |
|---|---|---|---|
| `alpha` | 0.7 | p.2 | neighbourhood regularisation weight |
| `p` | 2 | p.2 | fuzzifier |
| `epsilon` | 0.001 | p.3 | centroid convergence tolerance |
| `max_iter` | 100 | p.3 | iteration cap |
| `bg_pct` | 5 | p.4 | background threshold percentile |
| `C` | *"user-chosen; not fixed by the paper"* | **inferred** | number of tissue classes |
| `N_R` | 8 (2-D) or 26 (3-D) | **inferred** | neighbourhood cardinality |
| `w_beta` | 5 voxels per axis | **inferred** | bias-field mean-filter width |

That split is the point. The model did not pretend the paper specified `C`, `N_R` or
`w_beta` — it flagged them `inferred`, and the UI shows them with an amber chip while the
other five carry a green `p.N` chip that opens the verbatim sentence and deep-links to the
rendered page image. Stopping criterion, also extracted verbatim: *"Halt when
max_i |v_i^(t) − v_i^(t−1)| < epsilon = 0.001, or after 100 iterations."*

### 2. Dataset

`scripts/make_phantom.py` generates a 64³ T1-like phantom at 2 mm isotropic with four
tissue classes, Rician noise, and a smooth low-order multiplicative bias field. It is built
to be hard in exactly the way the technique addresses: the grey/white intensity gap is
realistic (0.55 vs 0.75) and the bias field is normalised over the brain mask, so a single
global intensity threshold cannot separate the tissues. A unit test asserts that
bias-corrected clustering beats bias-blind clustering on this data by **+0.196 mean Dice**
(0.4071 → 0.6031, identical 3-class k-means and identical brain mask on both sides — the
only difference is dividing by the true bias field). That margin is what makes the A/B
comparison capable of measuring anything.

> **What that test does and does not establish.** Both sides of it run a deliberately naive
> baseline: a crude `t1 > percentile(60)` brain mask and 1-D k-means with no spatial term.
> The +0.196 gap proves bias correction matters *to a naive method*, and 0.6031 is therefore
> a floor, not a ceiling. It is **not** evidence that the phantom is hard for a competent
> pipeline — and trials 3 and 4 below show it is not. An agent that builds a real brain mask
> (Otsu → largest connected component → fill holes) and adds a spatial prior reaches 0.997
> on the same volume. That distance between 0.60 and 0.997 is precisely the headroom the
> skill needed and did not get.

> The first version of the phantom failed that test. Its bias field was heavily smoothed
> white noise normalised over the whole cube, so the field's extremes landed on empty
> background and were nearly constant across the small central white-matter core — one
> global threshold still separated the tissues perfectly, and the "hard" benchmark was not
> hard. Two changes fixed it: a low-order polynomial field (which is also the standard model
> for real RF inhomogeneity) normalised over the **brain mask** rather than the volume, and a
> realistic grey/white contrast gap. The regression test exists so that cannot silently
> regress.

Generation is deterministic and resolution-independent: regenerating the phantom in a fresh
container produced byte-identical `t1.nii.gz` and `ground_truth.nii.gz` (sha256 prefixes
`0017937462254177` and `848c420f6e8f3be6`), which is why the generator is committed rather
than the 950 KB of volumes it emits.

Uploaded as two files: `t1.nii.gz` with `role=input`, `ground_truth.nii.gz` with
`role=ground_truth`. Only the first was ever staged into a sandbox.

### 3. A/B experiment — trial 1 (8-iteration budget)

Both arms concurrent, 14m20s wall clock.

| | Base agent | Skill-enabled agent |
|---|---|---|
| Status | completed | completed |
| Agent steps | 8 (budget exhausted) | 8 (budget exhausted) |
| Code executions | 7 | 7 |
| Failed executions | 1 | 4 |
| Runtime | 417 s | 799 s |
| Total tokens | 89,855 | 138,846 |
| Cost | 0 (this model is priced at 0) | 0 |
| Scorable prediction | **none produced** | `segmentation.nii.gz` |
| **Mean Dice** | **0.000** | **0.316** |

Per-class for the skill arm, after Hungarian label matching (`{0→0, 1→1, 2→3, 3→2}`):

| Class | Dice | IoU | Precision | Recall | Predicted mm³ | True mm³ | Volume error |
|---|---|---|---|---|---|---|---|
| CSF | 0.457 | 0.296 | 0.390 | 0.552 | 260,760 | 184,576 | +41.3 % |
| Grey matter | 0.491 | 0.325 | 0.460 | 0.527 | 271,624 | 237,120 | +14.6 % |
| White matter | 0.001 | 0.000 | 0.231 | 0.000 | 208 | 109,928 | −99.8 % |

**Read that headline carefully, because the interesting part is not the number.** The base
arm's 0.000 is `no_prediction_artifact` — not a bad segmentation. Artifact harvesting is
deliberately generous (it sweeps the workspace for anything that looks like a result, not
just files the agent declared with `save_artifact` — which is how the base arm's five
`.py` files were captured), but the base arm wrote its label volume to `/tmp/seg.npy`,
outside `/work/{run_id}`, where the sweep cannot see it. Its own final summary is worth
quoting:

> *"Working pipeline (executed successfully): Otsu brain mask → N4 bias correction →
> 3-class EM-GMM with MRF spatial regularization... The final label volume exists in memory
> / `/tmp/seg.npy`, but the four requested deliverable files were not yet written to disk or
> registered — the step budget expired during the mask-quality investigation. This is the
> primary incompleteness."*

So the base agent independently reached for a *more* sophisticated method than the paper's
(N4 + EM-GMM + a Potts MRF prior), diagnosed its own mask as biased, and spent its remaining
budget investigating that instead of shipping. The skill-enabled agent, handed a
specification with concrete constants and an explicit stopping rule, implemented BCFCM
directly in `bcfcm.py` and finished with registered artifacts — including the bias field and
memberships, which are intermediate products the *paper* says to compute.

On this trial the skill's apparent value was not a better algorithm — it was **convergence
within a fixed budget**. The skill arm's white-matter Dice of 0.001 is an honest bad result
even so: it under-segmented white matter almost completely while over-segmenting CSF. A run
that scores 0.316 is not a solved problem.

### 4. A/B experiment — trial 2 (8-iteration budget)

Same pinned `skill_version_id`, same dataset, new experiment. This is what an experiment
pinning an immutable skill version is *for*: no re-extraction, and the only thing that
varied was the model's sampling.

Both arms concurrent, 9m20s wall clock.

| | Base agent | Skill-enabled agent |
|---|---|---|
| Status | completed | completed |
| Agent steps | 8 (budget exhausted) | 8 (budget exhausted) |
| Code executions | 7 | 6 |
| Failed executions | 1 | 0 |
| Runtime | 523 s | 482 s |
| Total tokens | 77,815 | 92,613 |
| Scorable prediction | `seg_stage.npy` (an intermediate) | **none produced** |
| **Mean Dice** | **0.006** | **0.000** |

The sign flipped. This time the *skill* arm was the one that ran out of budget with nothing
registered. From its own final summary:

> *"| `segmentation.nii.gz` | Script writes it, but **execution result unconfirmed** |
> ... The final `run_python` execution of `bcfcm.py` completed within its window but I
> received no captured stdout or file confirmation before the budget ended... Additionally,
> no `save_artifact` calls were made for any output."*
>
> *"Tissue volumes cannot be reported as measured. Any numbers I gave would be fabricated."*

And the base arm's 0.006 is barely better than nothing: it registered `seg_stage.npy`, an
intermediate that the name ranking did not recognise as a segmentation but also did not
reject, and which assigned 1,558,808 mm³ to one class against a true 237,120 mm³.

### 5. A/B experiment — trial 3 (16-iteration budget)

Same pinned skill, freshly regenerated dataset (byte-identical ground truth —
sha256 prefix `848c420f6e8f3be6`, the same value trials 1 and 2 used, which is the
determinism claim above holding in practice). Both arms concurrent.

| | Base agent | Skill-enabled agent |
|---|---|---|
| Status | completed | completed |
| Agent steps | 15 (of 16) | 16 (budget exhausted) |
| Code executions | 12 | 14 |
| Failed executions | 0 | 3 |
| Runtime | 403 s | 953 s |
| Total tokens | 169,909 | 441,235 |
| Scorable prediction | `segmentation.nii.gz` | `segmentation.nii.gz` |
| **Mean Dice** | **0.9971** | **0.9948** |

Per-class, both arms:

| Class | Base Dice | Skill Dice |
|---|---|---|
| CSF | 0.9993 | 0.9989 |
| Grey matter | 0.9974 | 0.9954 |
| White matter | 0.9947 | 0.9902 |

**Both arms essentially solved the task.** The base agent's predicted volumes land within
0.6 % of truth on every class, on data whose labels it never saw:

| Tissue | Base predicted mm³ | True mm³ | Error |
|---|---|---|---|
| CSF | 184,416 | 184,576 | −0.09 % |
| Grey matter | 236,472 | 237,120 | −0.27 % |
| White matter | 110,560 | 109,928 | +0.58 % |

It got there without the paper, via `N4 bias correction → histogram-valley brain mask →
3-component GMM → MRF-ICM with a Potts prior (β = 0.35)` — a *more* elaborate pipeline than
the paper's BCFCM, arrived at independently and executed without a single failed run. The
skill arm implemented BCFCM as specified, swept its `w`/`β` neighbourhood parameters, and
landed 0.0023 lower for 2.4× the runtime and 2.6× the tokens.

<details>
<summary><b>These scores were re-verified against an independent implementation</b></summary>

A mean Dice of 0.997 is exactly the kind of number that should be distrusted before it is
published, so it was checked three ways rather than taken from the scorer:

1. **Ground-truth isolation, re-confirmed for these runs.** `ground_truth` appears **0**
   times across all four runs' `agent_steps` rows and **0** times across their `tool_calls`
   args and results. Only `t1.nii.gz` was ever staged.
2. **Independent re-scoring.** A standalone script — which does not import
   `app.evaluation` — reloaded each prediction and the ground truth straight from object
   storage and recomputed Hungarian-matched Dice from first principles. It reproduced
   0.9971, 0.9948 and 0.9802 exactly.
3. **The apparent conflict with the phantom test was explained, not ignored.** 0.997 sits
   far above that test's 0.6031, which looked wrong until the test was reread: its baseline
   is deliberately naive (crude percentile mask, 1-D k-means, no spatial term). The two
   numbers measure different things and do not contradict each other.

</details>

### 6. A/B experiment — trial 4 (16-iteration budget)

Same configuration again. This is the trial where the skill actively hurt.

| | Base agent | Skill-enabled agent |
|---|---|---|
| Status | completed | completed |
| Agent steps | 16 (budget exhausted) | 16 (budget exhausted) |
| Code executions | 14 | 15 |
| Failed executions | 2 | 5 |
| Runtime | 556 s | 968 s |
| Total tokens | 211,815 | 299,455 |
| Scorable prediction | `segmentation.nii.gz` | none — scored on `labels_tmp.npy` |
| **Mean Dice** | **0.9802** | **0.3052** |

The base arm repeated trial 3's result (CSF 0.9986, GM 0.9808, WM 0.9612). The skill arm
never wrote `segmentation.nii.gz` at all; the harvester fell back to an intermediate,
`labels_tmp.npy`, which under-segmented white matter by 88 %.

**Why it failed is the interesting part, and it is not bad luck.** Its 16 steps went to
`bcfcm.py`, then `ablate.py`, `ablate2.py`, and `reference.py` twice — an ablation harness
comparing BCFCM variants against a GMM reference. Five of those executions died on
`NameError`s while it patched variable definitions across successive rewrites (the surviving
scripts still carry its own `# <-- was missing` comments). It spent the run *validating the
technique* instead of shipping the deliverable.

That behaviour traces directly to the skill prompt, which instructs the agent to "run its
validation checks" — the paper's validation checks. On an unbounded budget that is good
science. On a 16-step budget it competes with the one action that gets scored. **The skill
made the agent behave more like a researcher and less like a deliverer, and the scoreboard
punished it for that.**

### What the four trials actually say

| | Trial 1 (b=8) | Trial 2 (b=8) | Trial 3 (b=16) | Trial 4 (b=16) |
|---|---|---|---|---|
| Base mean Dice | 0.000 (no artifact) | 0.006 (intermediate) | **0.9971** | **0.9802** |
| Skill mean Dice | 0.316 | 0.000 (no artifact) | 0.9948 | 0.3052 |
| Delta (skill − base) | **+0.316** | **−0.006** | **−0.0023** | **−0.6750** |
| Decided by | truncation | truncation | genuine quality | truncation (skill only) |

**The skill-enabled agent did not outperform the base agent in any trial where both arms
finished.** Raising the budget fixed the instrument — all four 16-iteration runs produced
real, scorable segmentations, where three of four 8-iteration runs produced none — and what
the repaired instrument shows is a **ceiling effect**:

1. **The base agent already solves this task.** 0.997 and 0.980 mean Dice, with volume
   errors under 0.6 %, reached with no access to the paper. There is almost no headroom
   above that for any skill to occupy. A benchmark on which the control scores 0.997 cannot
   measure the treatment.
2. **The phantom is the wrong difficulty for this model.** It was built to defeat
   bias-*blind* methods, and it does — the regression test still passes at +0.196. But
   defeating a naive baseline is not the same as challenging a frontier model with 16 steps
   and SimpleITK installed. The benchmark needs to get harder (heavier bias, lower SNR,
   partial-volume effects, or a real clinical volume) before an A/B on it means anything.
3. **The skill has a real cost, and trial 4 measured it.** Following a specification —
   implementing it faithfully, sweeping its parameters, running its ablations — consumes
   budget. When the technique is not needed to succeed, that cost is pure loss. This is a
   genuine finding about skill transfer, not a bug: **a skill can make an agent worse by
   directing effort toward rigour the task did not require.**
4. **N = 4 with an uncontrolled confound is still not a measurement.** Trials 1–2 and 3–4
   ran under different configurations, so only trials 3 and 4 are comparable to each other,
   and two samples cannot support a paired test. The honest statement is that no benefit was
   observed, not that no benefit exists.

What would actually answer the question: a harder dataset where the base agent scores in the
0.4–0.7 band, a budget large enough that neither arm is ever truncated, a `finalize` node
that forces one write-and-register pass for both arms identically, and N ≥ 10 paired trials.
The infrastructure to run all of that is built and verified end to end — the experiment is
sound; the *benchmark* is what needs to change.

I would rather ship this than ship trial 1's `+0.316` on its own with the delta in bold. The
system was built to be capable of telling me the skill does not help, and on this dataset
that is what it told me.

### Artifacts produced (trial 1)

`GET /api/experiments/{id}/download` returned a valid 1.22 MB archive
(`zipfile.testzip()` → `None`), verified live:

```
experiment.json                                800
skill/skill.json                            18,269
skill/skill.md                              10,181
base_agent/run.json                          3,314
base_agent/generated_code/explore.py           600
base_agent/generated_code/explore2.py          541
base_agent/generated_code/explore3.py        1,209
base_agent/generated_code/explore4.py          932
base_agent/generated_code/segment.py         3,741
skill_agent/run.json                         4,857
skill_agent/generated_code/explore.py          910
skill_agent/generated_code/explore2.py       2,212
skill_agent/generated_code/ascii_view.py       501
skill_agent/generated_code/bcfcm.py          6,177
skill_agent/outputs/segmentation.nii.gz     22,277
skill_agent/outputs/bias_field.npy       1,048,704
skill_agent/outputs/corrected_image.npy  1,048,704
skill_agent/outputs/memberships.npy        799,016
skill_agent/outputs/centroids.json             281
skill_agent/outputs/convergence.json           740
comparison/metrics.json                      6,913
```

No entry contains `ground_truth`.

### Asking the agent about its own run

The conversation panel on the experiment page answers from the recorded rows, not from
memory. Verbatim from this experiment (46 s, tools used:
`get_run_steps`, `list_artifacts`, `read_artifact_text`):

> **Q: Why did the base agent produce no segmentation file?**
>
> *"Of its 8 iterations, four went to throwaway exploration scripts (`explore.py`–
> `explore4.py`, all creating zero files), and then `segment.py` crashed on the first
> attempt:*
> ```
> RuntimeError: Exception thrown in SimpleITK N4BiasFieldCorrectionImageFilter_Execute:
> Inputs do not occupy the same physical space! InputImage Spacing: [1.0, 1.0, 1.0],
> InputImagePrimary Spacing: [2.0, 2.0, 2.0]
> ```
> *It fixed that and got `segment.py` to exit 0 twice — but by then the run hit the hard
> stop... Even the successful script never wrote a deliverable. Looking at `segment.py`, the
> final lines are* `np.save('/tmp/seg.npy', seg)`*... It dumps raw NumPy arrays to `/tmp`
> instead of writing a NIfTI segmentation into the workspace."*

That error message, that filename and that line of code all came out of `agent_steps` and
the stored artifact, not out of the model's imagination — which is the whole point of
persisting execution events rather than streaming and discarding them. It also
independently found the `/tmp` bug documented above.

A second question (32 s, one `get_skill` call) produced a correct 5-quoted / 3-inferred
parameter table with the exact source sentence for each quoted one.

### Things these runs demonstrated incidentally

- The **429 retry path is exercised in practice**, not hypothetically. From the worker log
  during trial 1: `openrouter TRANSPORT retry: upstream rate limit (429), throttle 1/5;
  backing off 2.0s — 'stealth/ox-alpha is temporarily rate-limited upstream'`. The run
  continued and completed.
- **Failed executions are recovered from, not fatal.** Trial 1's skill arm had 4 failed
  executions out of 7 and still finished with a complete artifact set. Trial 2's base arm
  recovered from a real SimpleITK error (`Inputs do not occupy the same physical space`) and
  went on to exit 0 — the repair-instruction path works.
- **Ground-truth withholding is observable in the event stream.** The dataset held two
  files; the first event of both arms reads `Staged 1 input file(s)`. The label volume never
  crossed the boundary.
- **No `reasoning` field appears in any SSE frame**, confirmed by reading the stream
  directly and inspecting every event's keys.
- **Artifact harvesting is generous and it mattered.** No arm in either trial called
  `save_artifact` on its scripts; every `.py` file in the archives was captured by the
  workspace sweep, as were trial 2's `explore_slices.png` and `gmm_params.npy`.
- **Skill-version pinning works as designed.** Trial 2 reused trial 1's exact
  `skill_version_id` with no re-extraction — a 5m28s saving, and the guarantee that the two
  trials differ only in sampling.
- **The base arm's `/tmp/seg.npy` is outside the workspace.** Files written there are neither
  harvested nor visible to `list_files`, and the system prompt does not currently warn
  against it (see [Known limitations](#known-limitations)).
- **The agents refuse to fabricate.** Trial 2's skill arm, unable to confirm its own script's
  output, wrote *"Tissue volumes cannot be reported as measured. Any numbers I gave would be
  fabricated."* rather than inventing a table. That is the behaviour the grounding rules ask
  for, arriving unprompted.

---

## Using a different paper, dataset or modality

Nothing is hard-coded to MRI or to one paper.

- **A different paper**: upload any PDF through the UI, or drop it at `fixtures/paper.pdf`
  and the seed script uses it instead of the bundled sample. The extraction schema is
  modality-agnostic; `modality` is a field the model fills in.
- **A different dataset**: create a dataset in the UI and upload files with roles. Only
  `input` and `aux` are staged into the sandbox; `ground_truth` never is.
- **A different modality**: the loader registry is the extension point. An EM TIFF stack or
  an H&E microscopy image already loads through the existing adapters; a genuinely new
  format is one `register_adapter([".ext"], fn)` call in
  `backend/app/imaging/loaders.py` and zero changes to the core. Slice rendering,
  overlays, `inspect_image`, the evaluator and the ZIP export all work off the normalised
  array and metadata, so they pick it up for free.
- **A different task**: the task prompt is free text on the experiment. The only convention
  worth respecting is naming the primary output so the evaluator can find it (see
  [Evaluation](#evaluation)).
- **A different model**: set `OPENROUTER_MODEL`. Everything goes through one client.

---

## Known limitations

Stated honestly, including the uncomfortable ones.

- **The benchmark saturates, so it cannot currently measure what it was built to measure.**
  This is the single biggest scientific weakness of the setup. With an adequate budget the
  *base* agent scores **0.997** and **0.980** mean Dice on the phantom with no access to the
  paper (trials 3 and 4). There is no headroom left for a skill to demonstrate value. The
  phantom was designed to defeat bias-*blind* methods and it still does — but defeating a
  naive baseline is not the same as challenging a frontier model that has 16 steps and
  SimpleITK. Until the task is hard enough that the base arm lands somewhere in the 0.4–0.7
  band, a null result here is uninformative about skill transfer in general.
- **Across four trials the skill arm never beat the base arm, and once it lost badly.**
  Deltas were **+0.316**, **−0.006**, **−0.0023** and **−0.6750**. Only the first two of
  those are even attributable to the skill's content; the +0.316 was a truncation artifact
  and the −0.6750 came from the skill arm spending its budget on the paper's ablation and
  validation checks instead of writing its deliverable. Reported as found. OpenRouter
  provides no reproducibility guarantee for this model and `temperature=0` is not one either,
  so a rigorous claim still needs N ≥ 10 paired trials with confidence intervals.
- **A skill can cost more than it returns, and this is a real result rather than a bug.**
  Trial 4's skill arm followed its instruction to run the technique's validation checks,
  built an ablation harness, lost five executions to `NameError`s while repairing it, and
  finished with no `segmentation.nii.gz`. Specification-following consumes budget; when the
  technique is not needed to succeed, that spend is pure loss. The skill card's "run its
  validation checks" line is the specific text responsible, and it is worth reconsidering
  for budgeted runs.
- **The iteration budget dominated the first two recorded trials, and they should be read
  with that in mind.** They ran with `AGENT_MAX_ITERATIONS=8`; all four of those runs
  exhausted it and three ended with the agent describing deliverables it had never written,
  so the comparison measured "did this arm reach `save_artifact` in time" rather than "did
  the skill help". The default is now 16 and agents are told where outputs must be written to
  survive. Trials 1 and 2 are kept **as they were run**, under the old budget, rather than
  quietly deleted once better numbers existed. The distinction that justified changing the
  budget at all: both arms failed the same way, so it was a broken instrument, not a losing
  result — and the change did not rescue the skill arm, which is the point.
- **Nothing forces a final write-and-register pass.** The analysis graph's `summarize` node
  asks for a written summary when the budget is spent, but it does not give the agent one
  last chance to persist its outputs. A `finalize` node that does — identically for both
  arms, so the fairness contract holds — would remove the failure mode above.
- **Slice navigation was stuck at one slice in the browser — since fixed, but worth recording
  because of how it hid.** `hooks/useSliceCount.ts` reads the `X-Slice-Count` header with
  `fetch(url, {method: "HEAD"})`, but FastAPI registers every `@router.get` route as `GET`
  only and does not synthesise a `HEAD` handler the way bare Starlette does. Every probe
  returned **405**, the hook's `.catch()` swallowed it, and the count fell back to `1` — so
  the axis tabs and the alpha slider worked and the failure looked like a volume that
  happened to have a single slice, rather than a rejected request. The rendering endpoints
  were correct throughout: `GET .../slice?axis=coronal&index=32` returned a valid PNG with
  `X-Slice-Count: 64` on all three axes. The two slice routes now declare
  `methods=["GET", "HEAD"]`; `HEAD` is the right verb, since the probe wants a header rather
  than a PNG, and Starlette drops the body. The lasting lesson is that the entire suite was
  green while a headline feature did nothing, because nothing exercised the request method
  the browser actually uses — a contract between two layers that each unit test, in
  isolation, was happy with.
- **Three high-severity transitive npm advisories remain**, in `postcss` and `sharp` inside
  Next 15. A critical advisory plus two highs were already cleared by pinning `next` to
  15.5.23. The remaining three are only fixable by moving to Next 16, a semver-major change
  to the App Router stack, which was not a sensible thing to take on late in the project.
  They are documented rather than hidden.
- **Skill extraction takes 4–7 minutes per paper** against `stealth/ox-alpha` (measured:
  5m28s for the 4-page sample via the API, and two back-to-back extractions in 8m27s in
  `test_real_extraction.py`), and a full two-arm experiment takes 9–15 minutes (measured:
  14m20s and 9m20s). The model is slow under load and
  genuinely returns 429s; transient DNS failures also occur. Every timeout, poll interval
  and keepalive in this project is sized for that reality, not for a fast model.
- **The OpenRouter key used here has a $1 credit ceiling**, and calls to this model currently
  report `cost: 0`. The cost column is wired end to end and reads zero.
- **`alembic revision --autogenerate` was never run against a live database.** The initial
  migration was written from the model metadata by hand, formatted the way autogenerate
  formats. The mitigation is a test that AST-parses the migration file and asserts it creates
  exactly the tables and columns the SQLAlchemy models declare, so the two cannot drift
  silently — but it is not the same thing as a real autogenerate diff.
- **The sandbox's `setrlimit` limits apply on POSIX only.** In the deployed Linux container
  they are always active. On a Windows development host that code path is guarded off and
  only the wall-clock timeout and path containment remain. The guard exists so the test suite
  runs on Windows, not because the limits are optional.
- **Path containment uses a string-prefix comparison**, not `Path.is_relative_to`. Run ids
  are sanitised to alphanumerics plus `-_` which makes a sibling-prefix collision hard to
  reach, but it is a prefix test, not a path-component test.
- **Execution isolation is per-workspace, not per-container.** All runs share one sandbox
  process and are separated by directory plus rlimits. A kernel-level escape would not be
  contained by directory separation. The production evolution is one ephemeral container per
  execution.
- **On timeout, only the direct child is killed.** The child gets its own session via
  `setsid()`, but nothing calls `killpg`, so a grandchild the agent spawned could outlive the
  kill until the container is recycled.
- **On Windows, Hyper-V reserves scattered TCP ranges** and port 8000 is commonly inside one.
  It presents as a confusing bind-permission error. `API_PORT` exists for exactly this.
- **Single user, no authentication.** There is one implicit workspace. Auth is out of scope
  per the brief, and the schema has `users` and `workspaces` ready for it.
- **Only one prediction artifact per run is scored**, chosen by the ranking described above.
  A run producing several plausible segmentations is scored on one of them.
- **Writing outside the workspace still loses the file — now warned against, not prevented.**
  Artifact harvesting sweeps `/work/{run_id}` generously, but an agent that writes to `/tmp`
  — which exists, is writable, and is where `HOME` points — loses that file entirely. This
  happened in trial 1 and caused that base arm's 0.000. `SHARED_PREAMBLE` now says so
  explicitly, to *both* arms identically (adding it to one only would be a fairness
  confound), and no run since has lost an output that way. It remains guidance rather than
  an enforced boundary.
- **"Produced nothing scorable" and "produced a bad segmentation" both read as Dice 0.0** in
  the headline number. The distinction is preserved in the metric's `value_json` detail
  (`error: no_prediction_artifact`) and in the exported `comparison/metrics.json`, but the
  single top-line figure does not carry it and neither does the comparison table.
- **`inspect_image`, `read_text` and `save_artifact` are workspace-relative by design**, so
  the agent has no way to inspect or rescue a file it put outside the workspace.
- **The synthetic phantom is easier than real BrainWeb data — and trials 3 and 4 quantified
  how much that matters.** The base agent reaches 0.997 on it unaided, which is the ceiling
  effect described above. It is committed as a generator so the demo works offline and
  deterministically; `scripts/fetch_brainweb.py` pulls the real thing when the network
  allows, and that is the harder benchmark the comparison actually needs.
- **LangGraph checkpoints enable resume, but there is no resume button in the UI yet.** The
  state is there and keyed by run id; the endpoint and the button are not.
- **`extract_skill_job` swallows its exception** and returns `{ok: False}` after marking the
  paper failed, so arq sees a success and never uses its one retry for extraction. That is
  the right behaviour for a deterministic parse failure and the wrong one for a transient
  network blip.
- **The conversation is not streamed.** It is one request/response per message, and a
  tool-heavy answer can take a while with no token-level feedback.

---

## What I would do with more time

- **Make the benchmark hard enough to have headroom.** This is now the top priority, because
  the budget fix already landed and revealed the real blocker: the base agent scores 0.997
  unaided, so there is nothing for a skill to add. Real BrainWeb data via
  `scripts/fetch_brainweb.py`, heavier bias fields, lower SNR, and partial-volume effects
  should put the base arm in the 0.4–0.7 band where a difference can actually show up. It is
  listed first because the evidence says so, not because it is the most interesting.
- **Add a forced final write-and-register pass** (a `finalize` node, identical for both arms),
  so a run can never end holding an unsaved result. Trial 4's skill arm lost on exactly this.
- **N-trial experiments with confidence intervals** rather than a single A/B pair, with a
  paired statistical test across trials, and a run-level dashboard that separates
  "no deliverable" from "poor deliverable" instead of collapsing both to Dice 0.
- **Separate "budget spent on the technique" from "budget spent shipping".** Trial 4 showed a
  skill can lose by being followed too faithfully. Measuring where each arm's steps go —
  exploration, implementation, validation, delivery — would turn that anecdote into data.
- **One ephemeral container per execution**, with cgroup limits, a read-only root filesystem
  and a per-run volume — replacing directory separation with kernel-level isolation.
- **A skill library**: cross-paper reuse, skill composition, and diffing two versions of the
  same skill to see what a re-extraction changed.
- **Human-in-the-loop skill editing** before the run, so a domain expert can correct an
  inferred parameter and the provenance chip records that a human, not the model, supplied it.
- **A third "ablated skill" arm** — the skill with its numeric parameters stripped — to
  separate "the paper told it the algorithm" from "the paper told it the constants".
- **niivue** for true 3-D volume rendering alongside the current server-rendered slices.
- **Resume from checkpoint in the UI**, exposing the state that is already persisted.
- **Move to Next 16** to clear the remaining transitive advisories.
- **Token streaming in the conversation panel**, which the OpenRouter client already
  supports and only the API and UI lack.

---

## Repository layout

```
.
├── docker-compose.yml          # 8 services, 3 networks, sandboxnet internal
├── .env.example                # every setting, documented
├── Makefile                    # up / demo / verify / test targets
├── README.md
├── scripts/
│   ├── make_phantom.py         # deterministic bias-field brain phantom + ground truth
│   ├── make_sample_paper.py    # synthetic methods paper (the real one is copyrighted)
│   ├── fetch_brainweb.py       # real BrainWeb data when the network allows
│   ├── seed_demo.py            # paper -> skill -> dataset -> A/B, over HTTP
│   └── verify_stack.sh         # 27 infrastructure + security checks
├── fixtures/                   # sample paper; phantom volumes are generated here
├── sandbox/
│   ├── Dockerfile              # pre-baked scientific stack, uid 1000
│   ├── requirements.txt
│   └── executor/{server,runner}.py
├── backend/
│   ├── Dockerfile  pyproject.toml  alembic/
│   ├── app/
│   │   ├── main.py  config.py
│   │   ├── db/{base,session,models/*}
│   │   ├── storage/s3.py
│   │   ├── api/routers/{health,papers,datasets,experiments,conversations,events}.py
│   │   ├── agents/
│   │   │   ├── llm.py                 # the OpenRouter client
│   │   │   ├── skill_extraction/      # graph, schema, prompts, validation
│   │   │   ├── analysis/              # the one graph both arms run
│   │   │   ├── conversation/          # read-only grounded chat
│   │   │   ├── tools/sandbox_tools.py # the tool list, identical per arm
│   │   │   └── checkpointing.py
│   │   ├── datasets/staging.py        # the ground-truth chokepoint
│   │   ├── sandbox/client.py
│   │   ├── imaging/{loaders,render}.py
│   │   ├── evaluation/metrics.py
│   │   ├── events/bus.py
│   │   ├── services/{papers,datasets,experiments,artifacts,export}.py
│   │   └── worker/{settings,tasks}.py
│   └── tests/{unit,integration}
└── frontend/
    ├── Dockerfile  next.config.ts
    ├── app/{papers,datasets,experiments}/…
    ├── components/{ComparisonView,SkillInspector,SliceViewer,AgentTimeline,ChatPanel,…}
    └── hooks/{useRunEvents,useSliceCount}.ts
```

The brief's suggested paper is Ahmed et al., *A Modified Fuzzy C-Means Algorithm for Bias
Field Estimation and Segmentation of MRI Data*. It is IEEE-copyrighted and is **not**
committed. `scripts/make_sample_paper.py` generates a synthetic stand-in that paraphrases the
same technique — bias-corrected, neighbourhood-regularised fuzzy c-means, with real
equations, real parameter values and a real convergence criterion — in text this project
owns, so extraction quality is still meaningful. Drop the real PDF at `fixtures/paper.pdf`
to run against it locally.
