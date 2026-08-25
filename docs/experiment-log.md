# Experiment log

Every A/B trial run against the real model, including the ones that failed and the
ones that contradict each other. The short version is in the
[README](../README.md#did-the-skill-help); this is the evidence behind it.


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
(`zipfile.testzip()` → `None`), verified live. The `paper/` entries were added after this
trial ran and are shown here at the sizes the same endpoint returns today:

```
experiment.json                                800
paper/source.pdf                             4,438
paper/paper.json                               287
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
  against it (see [Known limitations](limitations.md)).
- **The agents refuse to fabricate.** Trial 2's skill arm, unable to confirm its own script's
  output, wrote *"Tissue volumes cannot be reported as measured. Any numbers I gave would be
  fabricated."* rather than inventing a table. That is the behaviour the grounding rules ask
  for, arriving unprompted.

---

