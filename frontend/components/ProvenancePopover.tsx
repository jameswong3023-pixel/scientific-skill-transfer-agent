"use client";

import { useState } from "react";
import { BookOpen, Sparkles } from "lucide-react";

import type { Provenance } from "@/lib/types";

export function ProvenanceTag({
  provenance, inferred, paperId,
}: { provenance?: Provenance | null; inferred: boolean; paperId?: string | null }) {
  const [open, setOpen] = useState(false);

  if (inferred || !provenance) {
    return (
      <span
        title="Not stated in the paper — supplied by the extractor"
        className="inline-flex items-center gap-1 rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-300"
      >
        <Sparkles size={11} /> inferred
      </span>
    );
  }

  return (
    <span className="relative inline-block">
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-xs text-emerald-300 hover:bg-emerald-500/20"
      >
        <BookOpen size={11} /> p.{provenance.page}
      </button>
      {open && (
        <div className="absolute left-0 z-30 mt-1 w-96 rounded-lg border border-[var(--border)] bg-[#0f1421] p-3 shadow-xl">
          <p className="mb-2 text-xs uppercase tracking-wide text-slate-500">
            Quoted from page {provenance.page}
          </p>
          <blockquote className="border-l-2 border-emerald-500/50 pl-3 text-sm italic text-slate-200">
            &ldquo;{provenance.quote}&rdquo;
          </blockquote>
          {paperId && (
            <a
              href={`/api/papers/${paperId}/pages/${provenance.page}`}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-block text-xs text-violet-400 hover:underline"
            >
              View page {provenance.page} &rarr;
            </a>
          )}
        </div>
      )}
    </span>
  );
}
