# Design decisions

The choices worth defending, what each one buys, and what it costs. Referenced from
the [README](../README.md#architecture).


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
| **Hungarian label matching before scoring** | Neither agent is told our label numbering. Calling grey matter `2` when we call it `1` is not a segmentation error and must not score zero. | Background is pinned to itself rather than matched — see [Evaluation](../README.md#evaluation) for the bug that forced this. |
| **The phantom generator is committed, not the phantom** | `.gitignore` excludes `*.nii.gz` so large binaries stay out of git. Generation is deterministic for a given seed, so every reviewer gets an identical phantom without the repo carrying volumes. | One extra step on first run, handled automatically by the seed script. |
| **`skill_versions` is append-only, and an experiment pins one** | Re-extracting a skill creates version N+1 and leaves prior experiments reproducible against exactly the skill text they ran with. | None worth mentioning. |

---

