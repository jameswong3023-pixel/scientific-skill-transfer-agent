"use client";

import { useEffect, useState } from "react";
import { Download } from "lucide-react";

import { AgentTimeline } from "@/components/AgentTimeline";
import { ArmBadge } from "@/components/ArmBadge";
import { ArtifactList } from "@/components/ArtifactList";
import { ChatPanel } from "@/components/ChatPanel";
import { MetricsTable } from "@/components/MetricsTable";
import { SliceViewer } from "@/components/SliceViewer";
import { Panel } from "@/components/ui/Panel";
import { StatusPill } from "@/components/ui/StatusPill";
import { useRunEvents } from "@/hooks/useRunEvents";
import { api } from "@/lib/api";
import type { Arm, Artifact, Comparison } from "@/lib/types";

const SEG_HINTS = ["segmentation", "segment", "labels", "mask", "classes", "tissue"];

function segmentationOf(artifacts: Artifact[]): Artifact | undefined {
  const volumes = artifacts.filter(
    (a) => a.kind === "output" && /\.(nii(\.gz)?|npy|tiff?|mgz)$/i.test(a.path),
  );
  return (
    volumes.find((a) => SEG_HINTS.some((h) => a.path.toLowerCase().includes(h))) ?? volumes[0]
  );
}

function previewOf(artifacts: Artifact[]): Artifact | undefined {
  return artifacts.find((a) => a.kind === "figure");
}

export function ComparisonView({ initial }: { initial: Comparison }) {
  const [comparison, setComparison] = useState(initial);
  const running = ["pending", "running", "evaluating"].includes(comparison.experiment.status);
  const { byArm, connected } = useRunEvents(comparison.experiment.id, running);

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

      <div className="grid gap-5 lg:grid-cols-2">
        {(["base", "skill"] as Arm[]).map((arm) => {
          const run = runOf(arm);
          const artifacts = artifactsOf(arm);
          const segmentation = segmentationOf(artifacts);
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
                <Panel title="Result" subtitle={segmentation.path}>
                  <SliceViewer
                    baseUrlFor={(axis, i) => api.artifactSliceUrl(segmentation.id, axis, i)}
                    overlayUrlFor={(axis, i, alpha) =>
                      api.artifactOverlayUrl(segmentation.id, axis, i, alpha)
                    }
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
      <ChatPanel experimentId={comparison.experiment.id} />
    </div>
  );
}
