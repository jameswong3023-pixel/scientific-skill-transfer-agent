# Scientific Skill Transfer Agent

Can an agent read a scientific paper, learn a procedural technique from it, and then use that
technique to solve an unseen analysis problem better than the same agent without it?

This application makes the answer visible. It extracts an executable *skill* from a methods
paper, runs the same agent twice on the same data — once with the skill in its system prompt,
once without — inside the same network-isolated sandbox, and compares the two runs visually
and quantitatively against withheld ground truth.

On this dataset the answer it produced was **no**. Across four A/B trials the skill-enabled
agent never beat the base agent. In the two trials where both arms ran to completion the base
agent scored 0.997 and 0.980 mean Dice without ever seeing the paper, which leaves a skill
almost nowhere to help. In one of those trials the skill arm scored 0.305 because it spent
its budget running the paper's validation checks instead of writing its deliverable — a real
cost of skill transfer, measured rather than assumed.

That is a finding about the benchmark being too easy, not a claim that skill transfer does
not work. The reasoning, all four trials and an independent re-verification of the scoring
are in [docs/experiment-log.md](docs/experiment-log.md). The system was built so that it
could return this answer, and it did.

Every number below was measured against a running stack, including the ones that are not
flattering.

## Contents

- [Quick start](#quick-start)
- [Requirements coverage](#requirements-coverage) — where each thing the brief asks for lives
- [Architecture](#architecture)
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
- [Did the skill help?](#did-the-skill-help)
- [What is weakest](#what-is-weakest)
- [Repository layout](#repository-layout)

Longer material lives beside this file: the [experiment log](docs/experiment-log.md),
the [design decisions](docs/design-decisions.md) with their costs, and the full
[limitations](docs/limitations.md).

---

## Quick start

You need Docker with Compose v2 and an OpenRouter API key. Nothing else.

```bash
cp .env.example .env            # then set OPENROUTER_API_KEY
docker compose up -d --build    # postgres, redis, minio, sandbox, api, worker, frontend
docker compose run --rm seed --wait
```

Open <http://localhost:3000>.

`seed` is a one-shot compose service behind the `tools` profile, so `docker compose up` never
starts it. It uploads a sample methods paper, extracts the skill, generates and uploads the
phantom dataset with the correct file roles, launches the A/B experiment, and with `--wait`
blocks until both arms are scored and prints the result. That takes 15–25 minutes. Drop
`--wait` to launch it and watch in the browser instead.

To check the infrastructure and security claims this file makes:

```bash
bash scripts/verify_stack.sh    # 27 checks; must print "27 passed, 0 failed"
```

<details>
<summary>Running the seed script from the host instead of in Docker</summary>

The script only speaks HTTP, but it also generates the phantom, so it needs `httpx`, `numpy`,
`scipy`, `nibabel` and `pymupdf`. The backend virtualenv has all five:

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # Windows: .venv/Scripts/pip
cd .. && backend/.venv/bin/python scripts/seed_demo.py --wait
```

Point it elsewhere with `SSTA_API=http://localhost:8200 ... seed_demo.py`.
</details>

<details>
<summary>Port 8000 is unavailable on my machine</summary>

On Windows, Hyper-V reserves scattered TCP ranges and 8000 is commonly inside one. Docker
reports `bind: An attempt was made to access a socket in a way forbidden by its access
permissions`, which looks like a permissions problem but is not — nothing is listening.
Inspect the reservations with `netsh interface ipv4 show excludedportrange protocol=tcp`.

Set `API_PORT=8200` (or anything free) in `.env`. Only the published host port changes;
container-to-container URLs are unaffected, and `scripts/verify_stack.sh` reads `API_PORT`
from `.env` the same way Compose does. The same knob exists for `FRONTEND_PORT`, `MINIO_PORT`
and `MINIO_CONSOLE_PORT`.
</details>

The `Makefile` wraps exactly the commands shown here: `make up`, `make down`, `make reset`,
`make logs`, `make demo`, `make verify`, `make venv`, `make test`, `make lint`,
`make test-integration`, `make test-e2e`. Each underlying command was run directly during
development. The recipes themselves were not, because `make` is not installed on the machine
this was built on, so if a target misbehaves the command it wraps is one line above it.

---

## Requirements coverage

Where each thing the brief asks for actually lives, so a specific claim can be checked without
reading the whole file first.

**Required technology.** OX Alpha through OpenRouter is the only gateway — every model call in
all three agents goes through `backend/app/agents/llm.py`, and no provider SDK is installed
anywhere in the tree. LangGraph does the core orchestration in `backend/app/agents/*/graph.py`:
two `StateGraph`s with branching, cycles and `AsyncPostgresSaver` checkpointing. The chat loop
is deliberately not a graph, for reasons given [below](#3-conversation). The backend is
FastAPI with SQLAlchemy 2.0 async, Alembic and arq. Everything starts with
`docker compose up -d --build`.

**Product workflow**, steps 1 to 8 of the brief:

| # | Requirement | Where |
|---|---|---|
| 1 | Upload a paper | `POST /api/papers`, `PaperUpload.tsx` |
| 2 | Extract a skill, inspectable with provenance | [Skill extraction](#1-skill-extraction), `SkillInspector.tsx` — quoted fields carry a clickable page chip, inferred ones are flagged |
| 3 | Provide a dataset, inspected before analysis | `POST /api/datasets/{id}/files`, the `inspect_image` tool |
| 4 | Run analysis in an isolated sandbox | [Sandbox](#sandbox-implementation) — zero egress, no secrets, uid 1000 |
| 5 | A/B experiment, fair by construction | [Experimental fairness](#experimental-fairness) — one prompt module, one divergence point |
| 6 | Show the agent working | [Progress streaming](#progress-streaming) — SSE, subscribe-then-replay, no raw model reasoning |
| 7 | Results: original input, both outputs, metrics, artifacts, history | `ComparisonView.tsx` — the input volume sits under each arm's overlay and all three viewers share one slice |
| 8 | Evaluation against withheld ground truth | [Evaluation](#evaluation) — Dice, IoU, precision, recall, volume error, plus system metrics |

**Frontend.** All eleven capabilities the brief lists are present: upload a paper, view
processing status, inspect the skill, upload or select data, start the analysis, watch
progress, ask questions, compare arms, inspect artifacts, visualise imaging output, download
results. The conversational interface answers each of the brief's example questions from real
database rows, and *"Show me slice 72."* moves the images rather than only describing them.

**Deliverables.** The application runs end to end, with four real A/B trials recorded in the
[experiment log](docs/experiment-log.md). `scripts/verify_stack.sh` asserts the infrastructure
and security claims in 27 checks. This README covers the ten topics the brief names:
architecture, [design decisions](docs/design-decisions.md), [agent design](#agent-design),
[LangGraph](#langgraph-structure), [OpenRouter](#openrouter-integration),
[data model](#data-model), [sandbox](#sandbox-implementation), [how to run](#quick-start),
[limitations](docs/limitations.md) and what I would do next.

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

The flow the brief describes maps onto it directly. A paper goes through the extraction graph
and becomes a `SkillVersion` — JSONB payload, rendered markdown, per-field provenance. That
skill is appended to the system prompt of one arm and not the other. Both arms then run the
same analysis graph against the same sandbox, writing artifacts to MinIO and steps to
Postgres. After both finish, a deterministic evaluator reads ground truth for the first and
only time, and the comparison UI and ZIP are built from what it found.

| Service | Image | Networks | Purpose |
|---|---|---|---|
| `frontend` | `node:20-alpine` → Next standalone | `edge` | UI; proxies `/api/*` to `api` |
| `api` | `backend/Dockerfile` | `edge`, `core`, `sandboxnet` | REST + SSE; runs migrations on boot |
| `worker` | same image as `api` | `core`, `sandboxnet` | arq worker; runs every graph |
| `sandbox` | `sandbox/Dockerfile` | `sandboxnet` only | Executes agent-written code |
| `postgres` | `postgres:16-alpine` | `core` | Domain tables + LangGraph checkpoints |
| `redis` | `redis:7-alpine` | `core` | arq queue + event pub/sub |
| `minio` | `minio/minio` | `core`, `edge` | S3-compatible object store |
| `seed` | same image as `api` | `core` | One-shot demo driver (profile `tools`) |

There are three networks rather than one. `core` carries credentials, and Postgres and Redis
publish no host port at all. `edge` is what the browser can reach. `sandboxnet` is declared
`internal: true`, carries no credentials, and has no route to the internet — that is the
primary isolation guarantee, and it is verifiable with `docker network inspect` instead of
being asserted in prose. `api` is the only service on all three and is the deliberate broker
between them.

The choices worth defending, and what each one costs, are in
[docs/design-decisions.md](docs/design-decisions.md).

---

## Agent design

Three agents, all going through the same OpenRouter client.

### 1. Skill extraction

`backend/app/agents/skill_extraction/`. The paper is not treated as retrieval context. It is
parsed into per-page text with page markers, and the model is asked to emit a structured,
executable specification through a forced function call.

`segment_methods` narrows long papers to the methodology pages, falling back generously to all
of them. `extract_skill` then makes one forced `emit_skill` call against the schema in
`schema.py` — 17 fields covering inputs, preprocessing, algorithm steps, equations,
initialization, parameters, stopping criteria, postprocessing, dependencies, validation checks
and known failure modes. Every algorithm step and every parameter carries either
`provenance {quote, page}` or `inferred: true`.

`validate_skill` involves no model. It checks step counts and ordering, that dependencies are
named, that a stopping criterion exists if any step mentions iteration, and above all that
every non-inferred quote actually appears on the page it claims. Quote matching normalises both
sides first — NFKC, ligature expansion, de-hyphenation across line breaks, curly-quote folding,
whitespace collapse, lowercase — because PDF extraction inserts hard line breaks mid-word and a
model quoting the paper silently repairs them, so matching raw strings would flag honest quotes
as hallucinations. Quotes under 12 normalised characters are rejected as too short to be
evidence. `repair` feeds the report back as a corrective turn and forces the call again, at most
twice; warnings never trigger it, only errors.

The result is persisted as an immutable `SkillVersion`. The UI renders it with a green `p.N`
chip beside every quoted field, opening the verbatim quote and deep-linking to the rendered PDF
page, and an amber `inferred` chip where the model supplied something the paper did not say.
That is what makes "the model read the paper" falsifiable rather than a claim.

### 2. Analysis

`backend/app/agents/analysis/`. A tool-using loop over the sandbox. Both arms run this graph.

The tools in `agents/tools/sandbox_tools.py` are identical for both arms: `list_files`,
`inspect_image` (shape, dtype, spacing, intensity range, percentiles, and whether the data
looks like a label map, without the agent writing loader code), `read_text`, `write_file`,
`run_python`, `list_packages`, and `save_artifact`.

`dispatch_tool` never raises. An unknown tool name returns a message listing the real tools and
noting there is no package installer. A missing argument returns a description of what was
missing. Anything else returns `Tool 'x' raised an error: …`. An exception would end the run;
a described error lets the agent adapt, which is the entire point of giving it a sandbox.

The shared preamble tells both arms the same things: the sandbox is isolated, there is no
network and no `pip install`, inspect before assuming, print diagnostics and read them, fix the
specific cause rather than rewriting from scratch, and verify numerically — "a segmentation
that assigns every voxel to one class is a failure even if the script exits 0."

### 3. Conversation

`backend/app/agents/conversation/`. A bounded ReAct-style loop, five rounds then a forced
tool-free answer, over six read-only tools: `get_experiment_summary`, `get_skill`,
`list_artifacts`, `read_artifact_text`, `get_run_steps` (with an `only_failures` filter) and
`get_metrics`. It cannot execute code or write files. It reads exactly the rows the UI renders.

A seventh tool, `show_slice`, is what stops the chat being a separate product bolted onto the
viewer. Asked "Show me slice 72." the agent calls it, and the answer arrives carrying a
directive that moves the original input and both arms to that slice before describing what is
on it. The tool still writes nothing — the frontend applies the directive. It is persisted on
the message row, so reopening a conversation puts the images back where the answer left them.
The model is asked for the 1-based number the user sees while the viewer indexes from 0, and
that conversion lives in one function rather than being split between the prompt and the
component. A malformed call moves nothing.

Grounding is by instruction and by construction. The agent is told to look a value up before
quoting it, to read the actual run steps when asked why something failed, and to check
provenance when asked where a parameter came from. Because the tools return real `agent_steps`
and `metrics` rows, "Why did the first segmentation fail?" is answered from recorded stderr.
Every failure path degrades to prose rather than raising.

This one is a plain async loop even though it lives in `graph.py`. It has no branching worth
modelling and no state worth checkpointing, so a graph would have been ceremony.

---

## LangGraph structure

```
Extraction:
START → segment_methods → extract_skill → validate_skill ──┬─(ok / budget spent)─→ finalize → END
                                ▲                          │
                                └────────── repair ◀───────┘  (errors, ≤ 2 passes)

Analysis:
START → plan → agent_step ──┬── tools ──┐
                            │           │  (loops back)
                            │◀──────────┘
                            └── summarize → END
```

In the extraction graph, `route_after_validation` returns `repair` or `finalize`. A hard error
finalises, `validation.ok` finalises, `repair_count >= 2` finalises, otherwise it repairs.
State carries `pages`, `title`, `skill`, `validation`, `repair_count`, `usage`, `error` and
`_repair_prompt`. That last key is declared in the `TypedDict` despite the leading underscore,
because LangGraph silently drops keys a node returns that the state does not declare — losing
the repair prompt made the repair loop a no-op that looked like it worked.

In the analysis graph, `route` returns `tools` or `summarize`. An error set on state
summarises, hitting the iteration budget summarises, pending tool calls go to tools, otherwise
it summarises.

There is no separate repair node. After a `tools` visit, if any `run_python` observation came
back failed, one corrective user turn is appended telling the model to diagnose from the
traceback, change only what is broken, not restart from scratch, and not re-run identical code.
Control then flows back to `agent_step` on the ordinary edge, so recovery is a normal iteration
and shows up as one in the metrics.

The budget is `AGENT_MAX_ITERATIONS`, default 16, counted per `tools` visit, with
`recursion_limit = budget * 3 + 12`. When it is spent, `summarize` appends a "you have reached
your step budget" turn and makes one final tool-free call, so a run always ends with a written
summary rather than a truncation. The arm never appears in the control flow.

### Checkpointing

`AsyncPostgresSaver` with `thread_id = run.id`. The same value is denormalised onto
`runs.thread_id`, indexed, so persisted graph state joins back to the domain record.

The checkpointer is attached best effort: both the import and the connect/`setup()` are
wrapped, and either failure logs a warning and yields `None`, compiling the graph with plain
in-memory state. The experiment is the product, and losing resumability is much cheaper than
losing the run. Unit tests pin both degradation paths.

LangGraph owns in-flight state and gives crash-resume for free. The domain tables own the
durable, queryable record — `agent_steps` in order, `tool_calls`, `artifacts`, `metrics`. Node
transitions write to both, the checkpoint automatically and `agent_steps` through the event
emitter, and they reconcile on `run.thread_id`. The split is deliberate: LangGraph checkpoints
are an implementation detail of the framework, and no UI, metric or reviewer should have to
parse them.

---

## Experimental fairness

Both arms receive an identical model, temperature, `max_tokens`, tool schema list, iteration
budget, sandbox image, staged dataset and task text. They run the same graph object. The only
difference is the string returned by `build_system_prompt(arm, skill)` in
`backend/app/agents/analysis/prompts.py`.

The `base` branch returns the shared preamble verbatim and raises `ValueError` if a skill is
passed, so "the base arm must never receive a skill" is enforced rather than remembered. The
`skill` branch returns the same preamble plus an `## Available technique` header plus the
rendered card.

`backend/tests/unit/test_experimental_fairness.py` fails the build if that stops being true. It
asserts the two prompts share a byte-identical prefix and that the remainder is only the skill
block, that both arms get the same `TOOL_SCHEMAS` object, that sampling parameters match, and —
as a source-level check — that the strings `arm == "skill"`, `arm == 'skill'` and `arm != "base"`
appear nowhere in the analysis graph module, so nobody can quietly reintroduce an
arm-conditional branch.

Ground truth is withheld structurally. Files with `role == 'ground_truth'` live under their own
object-storage prefix and are excluded by an allowlist, `STAGEABLE_ROLES = {input, aux}`, in
`stage_dataset()` — the single function through which any dataset byte reaches a sandbox.
Ground truth is read once, in the worker, after both runs have finished.

One caveat worth stating plainly: OpenRouter accepts a `seed` for this model but offers no
reproducibility guarantee, and `temperature=0` is not one either. Repeated runs vary. A single
A/B pair is one sample, not a proof.

---

## OpenRouter integration

`backend/app/agents/llm.py`. OpenRouter is the only gateway, and there is no provider SDK
anywhere in the tree.

Calls go to `{OPENROUTER_BASE_URL}/chat/completions`, model `stealth/ox-alpha` by default, with
OpenRouter's `HTTP-Referer` and `X-Title` attribution headers. Three entry points: `chat()`,
`structured()` which forces a function call and returns parsed arguments plus usage, and
`stream()`.

Structured output goes exclusively through forced `tool_choice`. A live probe on 2026-08-24
found that `response_format: {type: json_schema, strict: true}` is accepted by this model with
HTTP 200 and then silently ignored — it answers in markdown prose, and any code parsing that
response crashes at runtime. `response_format` appears nowhere in the codebase as a result.

Retries run on three independent budgets, logged distinctly so a rate limit is never confused
with a formatting failure. HTTP 429 gets five extra attempts with exponential backoff from 2s to
16s, capped at 30s, and this model genuinely rate-limits under load, so that path is exercised.
Transport errors and retryable statuses get three attempts, while any other 4xx raises
`PermanentOpenRouterError` immediately rather than burning the budget on something that will
never succeed. Structured output gets three calls when the model answers with prose instead of
calling the forced tool, each retry appending the offending reply and a corrective turn. An HTTP
200 whose body carries an `error` object — OpenRouter does this for body-level throttling — is
reclassified through the same path.

Timeouts are 900s across connect, read, write and pool. Individual calls routinely run for
minutes; a complete skill extraction was measured at 5m28s. Usage is accumulated in a `Usage`
dataclass summed across retries, landing in `runs.totals` and `metrics`. This model reports cost
0, so that column reads zero — the accounting is wired, the price is not.

Private reasoning is scrubbed rather than merely unused, because a live probe confirmed this
model does populate `message.reasoning` on ordinary tool-call responses. `_scrub_reasoning()`
strips `reasoning`, `reasoning_details` and `reasoning_content` from the body's top level and
from every `choices[i].message` and `choices[i].delta` before the raw body is attached to the
response. `LLMResponse` has no `reasoning` attribute and the frontend's event type has no such
field. The brief forbids surfacing raw reasoning, so it is removed at the boundary rather than
left to nobody reading it.

---

## Data model

Postgres, 16 domain tables. Large binaries never live in rows — only `storage_key` pointers
into MinIO. Every table has a UUID `id`, generated client-side so a service can derive an
object-storage key before the INSERT lands, and a timezone-aware `created_at`.

```
users(id, email✦)
workspaces(id, user_id→users⌫, name)

papers(id, workspace_id⌫, title, filename, storage_key, sha256⊙, page_count, status, error)
       status: uploaded → parsing → parsed → extracting → extracted | failed
paper_pages(id, paper_id⌫, page_number, text, char_count, image_storage_key)
       unique(paper_id, page_number)

skills(id, workspace_id⌫, paper_id→papers∅, name, slug⊙)
skill_versions(id, skill_id⌫, version, payload⬢, markdown, model, extraction_run_id,
               validation⬢)
       unique(skill_id, version) — append-only

datasets(id, workspace_id⌫, name, modality, description)
dataset_files(id, dataset_id⌫, role⊙, filename, storage_key, sha256, bytes, media_type,
              file_metadata⬢)
       role: 'input' | 'ground_truth' | 'aux'

experiments(id, workspace_id⌫, paper_id∅, skill_version_id∅, dataset_id∅, task_prompt,
            status⊙, config⬢, completed_at)
runs(id, experiment_id⌫, arm, status⊙, thread_id⊙, workspace_dir, started_at, finished_at,
     error, totals⬢)
       unique(experiment_id, arm) — exactly one run per arm

agent_steps(id, run_id⌫, seq, node, kind, title, detail, payload⬢)
       unique(run_id, seq) — this is what makes SSE de-duplication sound
tool_calls(id, run_id⌫, step_id→agent_steps∅, tool_name⊙, args⬢, result⬢, status, duration_ms)
artifacts(id, run_id⌫, kind⊙, path, storage_key, media_type, bytes, sha256,
          artifact_metadata⬢)
metrics(id, experiment_id⌫, run_id⌫ NULL, scope, key⊙, value_num, value_json⬢)
       scope: 'quality' | 'system' | 'comparison'

conversations(id, workspace_id⌫, experiment_id⌫, title)
messages(id, conversation_id⌫, role, content, tool_calls⬢)

⌫ ON DELETE CASCADE   ∅ ON DELETE SET NULL   ⊙ indexed   ✦ unique   ⬢ JSONB
```

Plus `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` and `checkpoint_migrations`, owned
by LangGraph and outside Alembic's control because the library owns their schema.

A few judgement calls worth naming. `skill_versions` is append-only and an experiment pins an
exact `skill_version_id`, so re-extracting a paper produces version N+1 without disturbing any
experiment that already ran. Deletes cascade along ownership edges — a paper owns its pages, a
run owns its steps — and null out along soft references like `experiments.paper_id`, so
deleting a paper does not destroy the experimental record citing it. The object-key layout
encodes the trust boundary: `datasets/{dataset_id}/{role}/{filename}` puts ground truth under
its own prefix, so a prefix listing of agent-visible inputs cannot reach it, while
agent-controlled paths under `runs/{run_id}/` go through a `_safe_relpath()` guard rejecting
absolute paths and `..` components. A `sha256` is stored on every uploaded and produced object,
which is what makes an experiment auditable after the fact.

There is one migration, `0001_initial`, creating all 16 tables with indexes, cascade rules and
named unique constraints. The `api` container runs `alembic upgrade head` before `uvicorn` on
every start, so a cold `docker compose up` provisions the schema with no manual step. Verified
against a genuinely empty database: `upgrade head` produced exactly the 16 domain tables plus
`alembic_version`, and `downgrade base` removed all 16 again.

---

## Sandbox implementation

`sandbox/` is a separate image and a separate service. Agent-generated code is never `exec`'d
in the API or the worker.

The image is `python:3.11-slim` with an exact-pinned scientific stack baked in — numpy, scipy,
scikit-image, scikit-learn, headless OpenCV, nibabel, SimpleITK, pydicom, tifffile, pandas,
matplotlib, Pillow, versions in `sandbox/requirements.txt` — and `MPLBACKEND=Agg`, so a
plotting call cannot block on a missing display.

It runs as uid 1000, re-asserted in compose, never root, attached only to `sandboxnet`. No
egress means no `pip install`, which is why `list_packages` exists as a tool and why the prompt
states the constraint up front. Its environment holds only `SANDBOX_WORK_ROOT`,
`SANDBOX_MAX_TIMEOUT_S` and `SANDBOX_MEMORY_MB` — no API key, no database URL, no S3
credentials — and the child process gets a freshly built environment inheriting nothing from the
server. The HTTP surface is seven endpoints, and no host port is published.

Resource limits are applied in a `preexec_fn`: `RLIMIT_AS` at 3072 MB by default, `RLIMIT_CPU`
at the request's wall-clock budget with a 5s grace, `RLIMIT_NOFILE` 1024, `RLIMIT_NPROC` 256,
`RLIMIT_CORE` 0, then `os.setsid()`. Wall clock is clamped to a 900s ceiling and enforced by
`subprocess.run(timeout=…)`, which SIGKILLs the child. On expiry the result is `exit_code=124`,
`timed_out=true`, partial output preserved, and a `[sandbox] killed after Ns wall-clock limit`
line appended to stderr — an ordinary observation the agent can react to, never an exception.

Path containment runs through `workspace_path()`, sanitising the run id, and
`resolve_in_workspace()`, which rejects absolute paths, `~` and drive letters, then resolves and
asserts the result is under `/work/{run_id}`. Every file-touching endpoint goes through it and
returns HTTP 400 on violation. Stdout and stderr are truncated at 200,000 characters keeping
head and tail, because a traceback is usually at the end and a shape printout at the beginning.

`SandboxClient.execute()` never raises: a transport failure or non-2xx becomes
`ExecutionResult(exit_code=-1, stderr="Sandbox unavailable: …")`, because the agent must always
receive an observation it can reason about. Its HTTP timeout is deliberately
`sandbox_timeout_s + 60` so the client observes the sandbox's verdict rather than inventing its
own. All of this is verified live by `scripts/verify_stack.sh` and `test_resilience.py`.

---

## Progress streaming

Long-running work reaches the browser over SSE.

The worker's emitter persists an `agent_steps` row and commits, then publishes to Redis
`run:{run_id}:events` and `experiment:{experiment_id}:events`. A publish failure logs a
warning, because a dead Redis must never fail an analysis.

`GET /api/experiments/{id}/events` subscribes first, then replays. It attaches to Redis,
waiting up to 5s for the subscription to land, buffers live frames in a queue, then reads
history from Postgres and emits it while recording `(run_id, seq)` keys, dropping any live
frame already covered. Subscribing before replaying closes the gap where an event published
during the history read would be lost by both paths. Events look like this:

```json
{"run_id":"…","arm":"skill","seq":12,"kind":"tool_call","node":"execute_code",
 "title":"Running segmentation.py","detail":"exit=1 shape mismatch","ts":"…"}
```

A 15-second keepalive goes out on every idle tick, and the stream closes with a terminal
`event: end` frame once the run reaches a terminal status. Fifteen seconds is short relative to
the multi-minute silences a single model call produces; long quiet stretches are normal here
and the client must not conclude the stream is dead. Headers are `Cache-Control: no-cache`,
`Connection: keep-alive` and `X-Accel-Buffering: no`, and payload newlines are escaped so a
multi-line detail cannot split a frame.

The frontend uses a plain `EventSource`, same-origin thanks to the Next rewrite so there is no
CORS and no polyfill, keeps its own `(run_id, seq)` de-duplication set, and lets `EventSource`
auto-reconnect — which is safe precisely because the server replays.

---

## Imaging and visualisation

`app/imaging/loaders.py` normalises every format to `(numpy array, metadata)` behind a one-line
adapter registration: NIfTI and MGH through nibabel, TIFF through tifffile, DICOM through
pydicom, ordinary bitmaps through Pillow, `.npy` through numpy. Anything unregistered, or any
adapter that throws, raises a typed `UnreadableImageError`, which the upload probe records in
`dataset_files.file_metadata` and the `inspect_image` tool surfaces as a normal observation.

Rendering is server-side. `GET /api/artifacts/{id}/slice?axis=axial&index=72&cmap=gray` returns
a PNG plus an `X-Slice-Count` header, so the client learns a volume's depth from a response
header and never parses a volume. It reads that header with a `HEAD` request, and both slice
routes register `GET` and `HEAD` as separate operations so the probe is not a 405 — see the
[limitations](docs/limitations.md) for how that once hid a completely dead scrubber. Masks
render as a separate transparent RGBA PNG through `/overlay?alpha=…`, using a 13-entry
colour-blind-safe palette with label 0 fully transparent. The UI stacks base and overlay as two
absolutely positioned images with axis tabs, a range scrubber, arrow-key navigation, an overlay
toggle and an alpha slider.

Two details in the comparison view are worth calling out, because both were wrong at some
point and neither looked wrong.

The base layer under each arm's overlay is the input volume, not the segmentation. Labels are
drawn over the anatomy they claim to describe, so a boundary can be judged; unticking the
overlay gives the before/after view. An earlier version stacked the segmentation over itself,
which renders perfectly and shows nothing.

And the volume an arm's viewer draws is not a guess. `evaluate_experiment` records the artifact
it actually read as `prediction_artifact` on the `mean_dice` metric, and the view renders that
path. The skill arm of trial 3 wrote both `brainmask.npy` and `segmentation.nii.gz`; a
name-contains check matched the brain mask first, and the page drew a binary mask beside a
four-class Dice of 0.9948 — two panels that each looked plausible and disagreed with each
other. The frontend now prefers the scored path and falls back to a ranking mirroring
`rank_prediction_candidates`, negative list included, only for a run with no score yet.

All three viewers — input, base arm, skill arm — share one `{axis, index}` held by
`ComparisonView`, because comparing two segmentations is only meaningful on the same slice, and
because it gives the conversational agent a single place to point at. `SliceViewer` stays
uncontrolled when those props are absent, which is how the dataset page uses it.

---

## Evaluation

`app/evaluation/metrics.py`. Deterministic, never a model.

Quality metrics are computed per class and averaged: Dice, IoU, precision, recall, and volume
error in mm³ using the ground-truth voxel spacing. Label permutation is handled by building the
full prediction × truth overlap matrix and solving it with the Hungarian algorithm. Neither
agent is told our numbering, so a correct segmentation that calls white matter 1 instead of 3
must not score zero.

Background is pinned to itself rather than included in the assignment. Matching every label
including background let a degenerate all-background prediction be rescued by relabelling
background as a foreground class: `np.zeros(...)` against `[0,1,1,2]` scored 0.33 instead of
0.0. Background is the one label both sides genuinely agree on, so it is excluded from the
permutation search.

A shape mismatch short-circuits to a structured `{"error": "shape_mismatch", "detail": …}`
result rather than an exception, so a run that produced a wrongly shaped volume still gets a
comparison page explaining why it scored zero.

A run may write several volumes, so candidates are ranked by name — `segmentation` beats
`segment` beats `labels` beats `label` beats `mask` beats `classes` beats `tissue` — with
anything matching bias, field, preview, overlay, histogram, input or corrected rejected
outright. Each candidate is then actually decoded and scored in order until one succeeds, so a
run that wrote both `bias_field.nii.gz` and `segmentation.nii.gz` is scored on the
segmentation, and a run whose top-ranked file fails to decode falls through rather than
reporting zero.

System metrics per arm: `agent_steps`, `code_executions`, `failed_executions`,
`runtime_seconds`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost`.

Evaluation is the first and only read of a `ground_truth` file, it happens in the worker after
both runs finish, and if the dataset has no ground truth it returns
`{"evaluated": false, "reason": "no ground truth in dataset"}` and the experiment still
completes with system metrics. Evaluation being unavailable must never be the same thing as the
run failing.

---

## Artifacts and export

Every file the agent registers with `save_artifact` is uploaded to MinIO under
`runs/{run_id}/{path}` and recorded in `artifacts` with kind, media type, size and sha256.
`GET /api/experiments/{id}/download` streams a ZIP:

```
experiment.json                       # id, task, status, config
paper/source.pdf                      # the uploaded paper, streamed from object storage
paper/paper.json                      # title, original upload name, sha256, page count
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

The paper is the provenance root of everything else in the archive: without it a reader cannot
check a quoted parameter against the sentence it came from. It is normalised to `source.pdf` to
match the brief's tree, with the real upload name preserved beside it in `paper.json`, and it
is streamed from object storage rather than inlined, because a PDF does not belong in the API
process's memory next to two segmentation volumes.

The archive is streamed in 8 MB chunks through a write-only, non-seekable sink, which makes
`zipfile` emit data descriptors — the documented way to stream one. Rewinding a shared
`BytesIO` between flushes corrupted every member header offset after the first, which is
invisible in a small test and guaranteed in a real export. A missing or unreadable object is
logged and skipped so one bad artifact does not cost the whole download.

---

## Failure handling

Every row is exercised by a test, and the sandbox rows run against the real sandbox in
`backend/tests/integration/test_resilience.py`.

The theme is that nothing an agent can provoke is allowed to become an exception. A failure the
agent caused comes back as an observation it can read and react to; a failure in our own
infrastructure degrades to a warning rather than losing the run.

| Failure | Response |
|---|---|
| PDF is malformed, empty, oversized, or has wrong magic bytes | Rejected at upload with HTTP 400 and a specific reason |
| PDF parses but is a scan | Per-page raster PNGs are stored; vision input is the fallback |
| Model answers with prose instead of the forced tool call | Three retries with a corrective turn, then `StructuredOutputError` |
| Model quotes a sentence not in the paper | Counted as unverified, raised as a validation error, drives a repair |
| Extracted skill fails validation | Repair loop, ≤ 2 passes, feeding the exact errors back |
| Generated code fails | Non-zero exit returns as an observation with stderr; a repair instruction is appended |
| Generated code never terminates, or exhausts memory | SIGKILL or `RLIMIT_AS`; `exit_code: 124` / non-zero, returned as an observation |
| Generated code tries the network, `pip install`, or to escape `/work` | `OSError` or `PathEscapeError` → HTTP 400 from the executor |
| Sandbox service is unreachable | `exit_code=-1` with an explanatory stderr; the agent sees an observation, not a crash |
| Malformed or unreadable image | Upload succeeds, error recorded in `file_metadata`, `inspect_image` reports it |
| Prediction has the wrong shape | Structured `shape_mismatch`, mean Dice 0, comparison page still renders |
| Dataset has no ground truth | Evaluation skipped with a reason; the run still completes |
| Redis is down, or the object store is slow at boot | Events still persist to Postgres; SSE degrades to history plus keepalives |
| One arm crashes | Marked `failed`; the other arm still renders and is still scored |
| Run crashes mid-way | LangGraph checkpoint under `thread_id = run.id` survives it; arq retries once |
| Model rate-limits (429) | Five backed-off retries, logged distinctly from transport errors |

---

## Security boundaries

Every claim here is checked by `scripts/verify_stack.sh` against the running stack, currently
27 of 27, and where it needs code, by the resilience suite.

The sandbox has no internet: `sandboxnet` is `internal: true` and the sandbox is attached to
nothing else, so probes to `1.1.1.1:53`, `8.8.8.8:53` and `openrouter.ai:443` all fail with
`OSError`. It holds no secrets: `OPENROUTER_API_KEY`, `DATABASE_URL`, `S3_SECRET_KEY` and
`REDIS_URL` are absent from its environment, verified by asserting `printenv` fails for each
while `api` and `worker` do have the key, so agent code reading
`os.environ['OPENROUTER_API_KEY']` raises `KeyError`. It is unprivileged: uid 1000, no
published host port, `tmpfs` `/tmp`, with the rlimits and wall-clock SIGKILL described above,
and every path resolved and asserted under `/work/{run_id}`.

Uploads are validated with an extension allowlist plus a magic-byte sniff for PDFs, size caps
of 60 MB for papers and 500 MB for dataset files, filename traversal rejection, and content
hashes on everything stored. Agent-chosen output paths are normalised and rejected if they
contain `..`.

Agent-generated code is never `exec`'d by the API or worker. It is treated as hostile input and
only ever crosses the HTTP boundary into the sandbox. Ground truth is withheld by an allowlist
in a single chokepoint and read only by the evaluator after both runs finish. Private model
reasoning is scrubbed at the client boundary rather than merely unused, because this model does
return it. CORS is an explicit allowlist rather than `*`, and in normal operation the browser
never needs it, because the Next.js rewrite makes every API call same-origin.

---

## Running the tests

```bash
# Unit: 287 passing, no services needed.
cd backend
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # POSIX: .venv/bin/pip
.venv/Scripts/python -m pytest tests/unit -q
.venv/Scripts/python -m ruff check .

# Integration + resilience: 21 passed, 7 skipped in ~45s. Runs inside the api container,
# because the containment tests must reach sandboxnet, which is internal.
docker compose exec -T -e RUN_INTEGRATION=1 api python -m pytest tests/integration -v

# Infrastructure and security posture against the live stack: 27 passed, 0 failed.
bash scripts/verify_stack.sh

# The full A/B experiment against the real model, extraction included: 15-25 minutes.
cd backend && RUN_E2E=1 python -m pytest tests/integration/test_full_experiment.py -v -s
```

Skips are deliberate and each says why. The `test_real_extraction` pair needs an
`OPENROUTER_API_KEY` and the sample paper, which is not copied into the backend image; run them
from a host checkout with the key exported. They pass in 8m27s and are the strictest check here
— one asserts `validation["unverified_quotes"] == 0`, that the model fabricated no quotes at
all.

Beyond the obvious, the suite pins experimental fairness (identical tool schemas and sampling
parameters, a byte-identical prompt prefix, and a source-level check for arm-conditional
branches), ground-truth isolation, compose posture (parsed from the compose file, so a sandbox
gaining a network or a secret fails at edit time rather than at deploy time), migration drift
(the initial migration is AST-parsed and diffed against the models), and hostile code
containment — infinite loops, memory bombs, `/etc/shadow` reads, egress attempts, reading the
API key from the environment, writing outside the workspace, `pip install` — all seven actually
submitted to the real sandbox and all returning contained failures with the API still healthy.

Two tests pin the experiment itself: one asserts bias-corrected clustering beats bias-blind
clustering on the phantom by a real margin, so if that stopped being true the A/B comparison
would be measuring nothing and the build should fail; the other asserts phantom determinism and
resolution independence.

What the suite does not pin: nothing exercises the browser's own request methods, which is why
the slice-navigation defect in the [limitations](docs/limitations.md) survived a green suite and
was only found by probing the live API by hand.

---

## Did the skill help?

No — not in any trial where both arms finished.

| | Trial 1 (budget 8) | Trial 2 (budget 8) | Trial 3 (budget 16) | Trial 4 (budget 16) |
|---|---|---|---|---|
| Base mean Dice | 0.000 (no artifact) | 0.006 (intermediate) | 0.9971 | 0.9802 |
| Skill mean Dice | 0.316 | 0.000 (no artifact) | 0.9948 | 0.3052 |
| Delta | +0.316 | −0.006 | −0.0023 | −0.6750 |
| Decided by | truncation | truncation | genuine quality | truncation (skill only) |

Raising the iteration budget from 8 to 16 fixed the instrument: all four 16-iteration runs
produced real, scorable segmentations, where three of four 8-iteration runs produced none. What
the repaired instrument shows is a ceiling effect.

The base agent already solves this task. It reaches 0.997 and 0.980 mean Dice with volume errors
under 0.6%, with no access to the paper, by way of N4 bias correction, a histogram-valley brain
mask, a Gaussian mixture and MRF-ICM refinement with a Potts prior. There is almost no headroom
left for a skill to occupy, and a benchmark on which the control scores 0.997 cannot measure the
treatment.

The phantom is the wrong difficulty for this model. It was built to defeat bias-blind methods
and it does — the regression test still passes at +0.196 — but defeating a naive baseline is not
the same as challenging a frontier model that has 16 steps and SimpleITK installed.

Trial 4 measured a real cost of skill transfer. Following a specification faithfully, sweeping
its parameters and running its ablations consumes budget. That arm built an ablation harness,
lost five executions to `NameError`s, and never wrote `segmentation.nii.gz`. When the technique
is not needed to succeed, that effort is pure loss — a skill can make an agent worse by
directing effort toward rigour the task did not require.

And N=4 with a configuration change midway is not a measurement. Only trials 3 and 4 are
comparable to each other, and two samples cannot support a paired test. The honest statement is
that no benefit was observed, not that no benefit exists.

Because 0.997 deserved suspicion, it was checked three ways: no `ground_truth` reference appears
in any of the four runs' `agent_steps` or `tool_calls` and every staging call passed exactly
`["data/t1.nii.gz"]`; an independent scoring script that does not import `app.evaluation`
reproduced 0.9971, 0.9948 and 0.9802 exactly; and the apparent conflict with a phantom test
asserting 0.6031 traces to that test using a deliberately naive baseline as a floor.

Full trial-by-trial detail, agent transcripts, generated code and the verification scripts are
in [docs/experiment-log.md](docs/experiment-log.md).

---

## What is weakest

In the order I would fix them. The complete list, with the debugging that produced it, is in
[docs/limitations.md](docs/limitations.md).

**The benchmark is saturated.** This is the real scientific weakness. A control scoring 0.997
cannot measure a treatment. The dataset needs heavier bias, lower SNR, partial-volume effects,
or a real clinical volume, until the base agent lands somewhere in the 0.4–0.7 band.

**Nothing forces a final write-and-register pass.** The `summarize` node asks for a written
summary when the budget is spent but gives the agent no last chance to persist its outputs. That
is precisely how trial 4's skill arm scored 0.305 despite doing competent work. A `finalize`
node applied identically to both arms would remove the failure mode.

**N=4 is not a result.** Ten or more paired trials with confidence intervals is the minimum for
the claim this project exists to make, and the infrastructure to run them is already built.

**A cold start from a fresh clone has not been booted.** A fresh clone builds all four images,
but every test above ran against a stack that was already up. It is the first thing a reviewer
does and it is the largest untested path.

**Three high-severity transitive npm advisories remain**, in `postcss` and `sharp` inside Next
15. A critical and two highs were already cleared by pinning `next` to 15.5.23; the rest need
Next 16, a semver-major move to the App Router stack that was not sensible to take on late.

---

## Repository layout

```
.
├── docker-compose.yml          # 8 services, 3 networks, sandboxnet internal
├── .env.example                # every setting, documented
├── Makefile                    # up / demo / verify / test targets
├── docs/
│   ├── experiment-log.md       # all four A/B trials, in full
│   ├── design-decisions.md     # what each choice buys and costs
│   └── limitations.md          # the full list, with the debugging behind it
├── scripts/
│   ├── make_phantom.py         # deterministic bias-field brain phantom + ground truth
│   ├── make_sample_paper.py    # synthetic methods paper (the real one is copyrighted)
│   ├── fetch_brainweb.py       # real BrainWeb data when the network allows
│   ├── seed_demo.py            # paper -> skill -> dataset -> A/B, over HTTP
│   └── verify_stack.sh         # 27 infrastructure + security checks
├── fixtures/                   # sample paper; phantom volumes are generated here
├── sandbox/
│   ├── Dockerfile              # pre-baked scientific stack, uid 1000
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
│   │   │   ├── conversation/          # grounded chat + show_slice
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

The brief's suggested paper is Ahmed et al., *A Modified Fuzzy C-Means Algorithm for Bias Field
Estimation and Segmentation of MRI Data*. It is IEEE-copyrighted and is not committed.
`scripts/make_sample_paper.py` generates a synthetic stand-in paraphrasing the same technique —
bias-corrected, neighbourhood-regularised fuzzy c-means, with real equations, real parameter
values and a real convergence criterion — in text this project owns, so extraction quality is
still meaningful. Drop the real PDF at `fixtures/paper.pdf` to run against it locally.
