"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Spinner } from "@/components/ui/Spinner";
import { StatusPill } from "@/components/ui/StatusPill";
import { api } from "@/lib/api";

const STAGES = ["uploaded", "parsing", "parsed", "extracting", "extracted"];

export function PaperStatusWatcher({
  paperId, initialStatus,
}: { paperId: string; initialStatus: string }) {
  const router = useRouter();
  const [status, setStatus] = useState(initialStatus);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === "extracted" || status === "failed") return;
    const timer = setInterval(async () => {
      try {
        const paper = await api.getPaper(paperId);
        setStatus(paper.status);
        if (paper.status === "extracted") {
          clearInterval(timer);
          router.refresh();
        }
        if (paper.status === "failed") {
          clearInterval(timer);
          setError(paper.error ?? "extraction failed");
        }
      } catch {
        /* transient; keep polling */
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [paperId, status, router]);

  if (error) {
    return (
      <p className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
        {error}
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Spinner />
        <span className="text-slate-300">
          Reading the paper and building an executable skill. This usually takes a minute.
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {STAGES.map((s) => (
          <span key={s} className={STAGES.indexOf(status) >= STAGES.indexOf(s) ? "" : "opacity-30"}>
            <StatusPill status={s} />
          </span>
        ))}
      </div>
    </div>
  );
}
