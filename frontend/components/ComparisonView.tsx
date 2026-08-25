"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Download } from "lucide-react";

import { AgentTimeline } from "@/components/AgentTimeline";
import { ArmBadge } from "@/components/ArmBadge";
import { ArtifactList } from "@/components/ArtifactList";
import { ChatPanel } from "@/components/ChatPanel";
import { MetricsTable } from "@/components/MetricsTable";
import { SliceViewer, type Axis } from "@/components/SliceViewer";
import { Panel } from "@/components/ui/Panel";
import { StatusPill } from "@/components/ui/StatusPill";
import { useRunEvents } from "@/hooks/useRunEvents";
import { api } from "@/lib/api";
import type { Arm, Artifact, Comparison, DatasetFile, ViewDirective } from "@/lib/types";

// Mirrors `rank_prediction_candidates` in backend/app/services/experiments.py:
// strongest name hint first, and never a bias field or a corrected image.
const SEG_HINTS = ["segmentation", "segment", "labels", "label", "mask", "classes", "tissue"];
const NOT_SEG = ["bias", "field", "preview", "overlay", "histogram", "input", "corrected"];

/**
 * The volume to draw for an arm.
 *
 * `scoredPath` is authoritative: it is the artifact the evaluator actually read,
 * recorded on the metric. Guessing instead is how this went wrong — the skill
 * arm wrote both `brainmask.npy` and `segmentation.nii.gz`, a name-contains
 * check matched the brain mask first, and the page showed a binary mask beside
 * a four-class Dice of 0.9948. The picture has to be the thing that was scored.
 *
 * The heuristic below is only the fallback for a run with no score yet — still
 * in flight, or a dataset with no ground truth.
 */
function segmentationOf(artifacts: Artifact[], scoredPath?: string): Artifact | undefined {
  const volumes = artifacts.filter(
    (a) => a.kind === "output" && /\.(nii(\.gz)?|npy|tiff?|mgz)$/i.test(a.path),
  );
  if (scoredPath) {
    const scored = volumes.find((a) => a.path === scoredPath);
    if (scored) return scored;
  }
  const plausible = volumes.filter(
    (a) => !NOT_SEG.some((bad) => a.path.toLowerCase().includes(bad)),
  );
  const ranked = [...plausible].sort((a, b) => rank(b.path) - rank(a.path));
  return ranked[0] ?? volumes[0];
}

function rank(path: string): number {
  const low = path.toLowerCase();
  const i = SEG_HINTS.findIndex((h) => low.includes(h));
  return i === -1 ? 0 : SEG_HINTS.length - i;
}

/** The artifact the evaluator read for this arm, if it has been scored. */
function scoredPathOf(comparison: Comparison, arm: Arm): string | undefined {
  const detail = comparison.metrics.quality?.[arm]?.mean_dice?.detail as
    | { prediction_artifact?: string }
    | undefined;
  return detail?.prediction_artifact;
}

function previewOf(artifacts: Artifact[]): Artifact | undefined {
  return artifacts.find((a) => a.kind === "figure");
}

/** The volume the agents were given — never a ground-truth file, which is the
 *  reference the run is scored against rather than part of the input. */
function inputFileOf(files: DatasetFile[] | undefined): DatasetFile | undefined {
  const usable = (files ?? []).filter((f) => f.role === "input");
  return usable.find((f) => /\.(nii(\.gz)?|tiff?|mgz|dcm)$/i.test(f.filename)) ?? usable[0];
}

export function ComparisonView({ initial }: { initial: Comparison }) {
  const [comparison, setComparison] = useState(initial);
  const running = ["pending", "running", "evaluating"].includes(comparison.experiment.status);
  const { byArm, connected } = useRunEvents(comparison.experiment.id, running);

  // One slice position shared by the input and both arms. Comparing two
  // segmentations is only meaningful on the same slice, and it gives the chat's
  // `show_slice` a single place to point at.
  const [view, setView] = useState<{ axis: Axis; index: number }>({ axis: "axial", index: 0 });
  const [sliceCount, setSliceCount] = useState(0);
  const centredFor = useRef<string>("");

  const input = inputFileOf(comparison.dataset?.files);

  // Open on the middle slice — the informative one — once per axis, then leave
  // the user's scrubbing alone.
  const onCountChange = useCallback(
    (count: number) => {
      setSliceCount(count);
      const key = `${view.axis}:${count}`;
      if (count > 1 && centredFor.current !== key) {
        centredFor.current = key;
        setView((v) => ({ ...v, index: Math.floor(count / 2) }));
      }
    },
    [view.axis],
  );

  const showSlice = useCallback((directive: ViewDirective) => {
    setView((v) => ({
      axis: directive.axis ?? v.axis,
      index: Math.max(0, directive.index),
    }));
    document.getElementById("comparison-images")?.scrollIntoView({ behavior: "smooth" });
  }, []);

  // While the experiment is in flight the SSE stream drives the timeline; the
  // structured comparison (artifacts, metrics) is refetched periodically.
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => {
      api.getComparison(comparison.experiment.id).then(setComparison).catch(() => {});
    }, 5000);
    return () => clearInterval(timer);
  }, [running, comparison.experiment.id]);

  const runOf = (arm: Arm) => comparison.runs.find((r) => r.arm === arm);
  const artifactsOf = (arm: Arm) => {
    const run = runOf(arm);
    return run ? (comparison.artifacts[run.id] ?? []) : [];
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Experiment</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-400">
            {comparison.experiment.task_prompt}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusPill status={comparison.experiment.status} />
          {running && connected && (
            <span className="running text-xs text-violet-400">● live</span>
          )}
          <a
            href={api.downloadUrl(comparison.experiment.id)}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-slate-200 hover:bg-white/5"
          >
            <Download size={14} /> Download results
          </a>
        </div>
      </div>

      {input && (
        <Panel
          title="Original input"
          subtitle={`${input.filename} — the volume both agents were given`}
        >
          <div className="mx-auto max-w-md">
            <SliceViewer
              baseUrlFor={(axis, i) => api.datasetSliceUrl(input.id, axis, i)}
              axis={view.axis}
              index={view.index}
              onViewChange={setView}
              onCountChange={onCountChange}
            />
          </div>
          <p className="mt-2 text-center text-xs text-slate-500">
            Both results below are locked to this slice
            {sliceCount > 1 ? ` (${sliceCount} in this axis)` : ""}. Ask the agent to
            &ldquo;show me slice 72&rdquo; to jump.
          </p>
        </Panel>
      )}

      <div id="comparison-images" className="grid gap-5 lg:grid-cols-2">
        {(["base", "skill"] as Arm[]).map((arm) => {
          const run = runOf(arm);
          const artifacts = artifactsOf(arm);
          const scoredPath = scoredPathOf(comparison, arm);
          const segmentation = segmentationOf(artifacts, scoredPath);
          const preview = previewOf(artifacts);

          return (
            <div key={arm} className="space-y-4">
              <Panel
                title={<ArmBadge arm={arm} />}
                actions={run ? <StatusPill status={run.status} /> : null}
              >
                <AgentTimeline
                  events={byArm[arm]}
                  emptyLabel={run?.status === "pending" ? "Queued…" : "No events yet"}
                />
              </Panel>

              {segmentation && (
                <Panel
                  title="Result"
                  subtitle={
                    (input
                      ? `${segmentation.path} over ${input.filename}`
                      : segmentation.path) +
                    (segmentation.path === scoredPath ? " — the volume scored below" : "")
                  }
                >
                  {/* The labels sit on the anatomy they claim to describe, so a
                      boundary can actually be judged. Untick "overlay" for the
                      before/after the brief asks for. Without a dataset input
                      volume there is nothing to sit on, so fall back to the
                      labels alone rather than showing nothing. */}
                  <SliceViewer
                    baseUrlFor={(axis, i) =>
                      input
                        ? api.datasetSliceUrl(input.id, axis, i)
                        : api.artifactSliceUrl(segmentation.id, axis, i)
                    }
                    overlayUrlFor={(axis, i, alpha) =>
                      api.artifactOverlayUrl(segmentation.id, axis, i, alpha)
                    }
                    axis={view.axis}
                    index={view.index}
                    onViewChange={setView}
                  />
                </Panel>
              )}

              {!segmentation && preview && (
                <Panel title="Preview" subtitle={preview.path}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={api.artifactUrl(preview.id)}
                    alt={preview.path}
                    className="w-full rounded-lg border border-[var(--border)]"
                  />
                </Panel>
              )}

              {run?.totals?.summary && (
                <Panel title="Agent summary">
                  <p className="whitespace-pre-wrap text-sm text-slate-300">
                    {run.totals.summary}
                  </p>
                </Panel>
              )}

              <Panel title="Artifacts">
                <ArtifactList artifacts={artifacts} />
              </Panel>
            </div>
          );
        })}
      </div>

      <MetricsTable comparison={comparison} />
      <ChatPanel
        experimentId={comparison.experiment.id}
        onShowSlice={input ? showSlice : undefined}
      />
    </div>
  );
}
