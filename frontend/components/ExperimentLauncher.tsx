"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { api, ApiError } from "@/lib/api";
import type { Dataset, Paper } from "@/lib/types";

const DEFAULT_TASK =
  "Segment the provided MRI volume into its tissue classes (background, cerebrospinal " +
  "fluid, grey matter, white matter) and calculate the volume of each tissue type in mm³. " +
  "Save the segmentation as segmentation.nii.gz, the measurements as measurements.json, a " +
  "visual check as preview.png, and a short analysis_summary.md.";

export function ExperimentLauncher({
  papers, datasets,
}: { papers: Paper[]; datasets: Dataset[] }) {
  const router = useRouter();
  const search = useSearchParams();

  const [paperId, setPaperId] = useState(search.get("paper") ?? papers[0]?.id ?? "");
  const [datasetId, setDatasetId] = useState(search.get("dataset") ?? datasets[0]?.id ?? "");
  const [task, setTask] = useState(DEFAULT_TASK);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function launch() {
    setBusy(true);
    setError(null);
    try {
      let skillVersionId: string | null = null;
      if (paperId) {
        const skill = await api.getSkill(paperId).catch(() => null);
        skillVersionId = skill?.id ?? null;
      }
      const experiment = await api.createExperiment({
        dataset_id: datasetId,
        task_prompt: task,
        paper_id: paperId || null,
        skill_version_id: skillVersionId,
      });
      await api.runExperiment(experiment.id);
      router.push(`/experiments/${experiment.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2">
        <label className="block">
          <span className="text-sm text-slate-400">Paper (provides the skill)</span>
          <select
            value={paperId}
            onChange={(e) => setPaperId(e.target.value)}
            className="mt-1 w-full rounded-lg border border-[var(--border)] bg-black/30 px-3 py-2 text-slate-100"
          >
            <option value="">No paper — both arms identical (control)</option>
            {papers.filter((p) => p.status === "extracted").map((p) => (
              <option key={p.id} value={p.id}>{p.title ?? p.filename}</option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="text-sm text-slate-400">Dataset</span>
          <select
            value={datasetId}
            onChange={(e) => setDatasetId(e.target.value)}
            className="mt-1 w-full rounded-lg border border-[var(--border)] bg-black/30 px-3 py-2 text-slate-100"
          >
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>{d.name} ({d.modality})</option>
            ))}
          </select>
        </label>
      </div>

      <label className="block">
        <span className="text-sm text-slate-400">Task — given verbatim to both agents</span>
        <textarea
          value={task}
          onChange={(e) => setTask(e.target.value)}
          rows={5}
          className="mt-1 w-full rounded-lg border border-[var(--border)] bg-black/30 px-3 py-2 text-sm text-slate-100 outline-none focus:border-violet-500"
        />
      </label>

      <div className="rounded-lg border border-[var(--border)] bg-black/20 p-3 text-xs text-slate-400">
        Both agents receive the same task, the same data, the same tools, the same sandbox and
        the same model. The only difference is that the skill-enabled agent also receives the
        technique extracted from the paper.
      </div>

      {error && <p className="text-sm text-red-300">{error}</p>}

      <Button onClick={launch} disabled={busy || !datasetId}>
        {busy ? <><Spinner /> Starting…</> : "Run the A/B experiment"}
      </Button>
    </div>
  );
}
