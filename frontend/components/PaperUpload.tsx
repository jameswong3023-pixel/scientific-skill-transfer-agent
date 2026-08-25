"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Upload } from "lucide-react";

// NOTE: the plan also imported `Button` here, but this component renders a
// styled <label> file-picker and never uses it. Dropped to keep the module clean.
import { Spinner } from "@/components/ui/Spinner";
import { api, ApiError } from "@/lib/api";

export function PaperUpload() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onFile(file: File) {
    setBusy(true);
    setError(null);
    try {
      const paper = await api.uploadPaper(file);
      await api.extractSkill(paper.id);
      router.push(`/papers/${paper.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
      setBusy(false);
    }
  }

  return (
    <div>
      <label className="flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-[var(--border)] p-10 transition hover:border-violet-500/50 hover:bg-white/[0.02]">
        {busy ? <Spinner className="h-6 w-6" /> : <Upload size={26} className="text-slate-500" />}
        <span className="text-slate-300">
          {busy ? "Uploading and starting extraction…" : "Drop a methods paper (PDF) or click to browse"}
        </span>
        <span className="text-xs text-slate-500">
          The agent will read it and extract an implementable skill
        </span>
        <input
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          disabled={busy}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onFile(f);
          }}
        />
      </label>
      {error && (
        <p className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}
