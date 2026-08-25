"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { api, ApiError } from "@/lib/api";

export function DatasetCreate() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [modality, setModality] = useState("MRI");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <form
      className="flex flex-wrap gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!name.trim()) return;
        setBusy(true);
        setError(null);
        // The plan left this call unguarded, so a failed create would surface as an
        // unhandled promise rejection and the form would stay stuck on "busy".
        try {
          const d = await api.createDataset(name, modality);
          router.push(`/datasets/${d.id}`);
        } catch (err) {
          setError(err instanceof ApiError ? err.detail : String(err));
          setBusy(false);
        }
      }}
    >
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Dataset name"
        className="flex-1 rounded-lg border border-[var(--border)] bg-black/30 px-3 py-2 text-slate-100 outline-none focus:border-violet-500"
      />
      <select
        value={modality}
        onChange={(e) => setModality(e.target.value)}
        className="rounded-lg border border-[var(--border)] bg-black/30 px-3 py-2 text-slate-100"
      >
        {["MRI", "CT", "X-ray", "electron microscopy", "histopathology", "other"].map((m) => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
      <Button type="submit" disabled={busy}>{busy ? <Spinner /> : "Create"}</Button>
      {error && <p className="w-full text-sm text-red-300">{error}</p>}
    </form>
  );
}

export function DatasetFileUpload({ datasetId }: { datasetId: string }) {
  const router = useRouter();
  const [role, setRole] = useState("input");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm text-slate-400">Role</label>
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="rounded-lg border border-[var(--border)] bg-black/30 px-3 py-1.5 text-sm text-slate-100"
        >
          <option value="input">input — given to both agents</option>
          <option value="ground_truth">ground truth — withheld, used only for scoring</option>
          <option value="aux">auxiliary</option>
        </select>
      </div>

      <label className="flex cursor-pointer items-center justify-center gap-3 rounded-xl border-2 border-dashed border-[var(--border)] p-6 hover:border-violet-500/50">
        {busy ? <Spinner /> : <span className="text-sm text-slate-400">Add a file (.nii.gz, .tif, .dcm, .png, .npy)</span>}
        <input
          type="file"
          className="hidden"
          disabled={busy}
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            setBusy(true);
            setError(null);
            try {
              await api.uploadDatasetFile(datasetId, f, role);
              router.refresh();
            } catch (err) {
              setError(err instanceof ApiError ? err.detail : String(err));
            } finally {
              setBusy(false);
            }
          }}
        />
      </label>

      {role === "ground_truth" && (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-300">
          Ground-truth files are never copied into either agent&apos;s sandbox. They are read
          only after both runs finish, to compute the metrics.
        </p>
      )}
      {error && <p className="text-sm text-red-300">{error}</p>}
    </div>
  );
}
