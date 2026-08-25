# Limitations, and what I would do next

Written while the numbers were in front of me, so it records what actually broke
rather than what I remember breaking. Summarised in the
[README](../README.md#what-is-weakest).


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
  `X-Slice-Count: 64` on all three axes. Both slice routes now register `GET` and `HEAD`
  as two decorators on the same handler; `HEAD` is the right verb, since the probe wants a
  header rather than a PNG, and Starlette drops the body. (A single
  `api_route(methods=["GET", "HEAD"])` also works, but shares one operation id across both
  methods, which makes the generated OpenAPI schema ambiguous and warns on every boot.)
  The lasting lesson is that the entire suite was
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

