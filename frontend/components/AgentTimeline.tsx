"use client";

import clsx from "clsx";
import { useEffect, useRef } from "react";
import {
  AlertTriangle, CheckCircle2, Code2, FileOutput, Play, Search, Sparkles,
} from "lucide-react";

import type { RunEvent } from "@/lib/types";

const ICONS: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  plan: Sparkles,
  stage_data: FileOutput,
  inspect_data: Search,
  write_code: Code2,
  execute_code: Play,
  summarize: CheckCircle2,
  error: AlertTriangle,
};

function isFailure(event: RunEvent): boolean {
  const code = (event.payload as { exit_code?: number }).exit_code;
  return event.kind === "error" || (typeof code === "number" && code !== 0);
}

export function AgentTimeline({
  events, emptyLabel = "Waiting to start…",
}: { events: RunEvent[]; emptyLabel?: string }) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length]);

  if (events.length === 0) {
    return <p className="py-6 text-center text-sm text-slate-600">{emptyLabel}</p>;
  }

  return (
    <div className="max-h-[26rem] space-y-1.5 overflow-y-auto pr-1">
      {events.map((event) => {
        const Icon = ICONS[event.node] ?? Sparkles;
        const failed = isFailure(event);
        const stderr = (event.payload as { stderr_tail?: string }).stderr_tail;
        const created = (event.payload as { files_created?: string[] }).files_created;

        return (
          <div
            key={`${event.run_id}-${event.seq}`}
            className={clsx(
              "flex gap-2.5 rounded-md px-2.5 py-2 text-sm",
              failed ? "bg-red-500/10" : "hover:bg-white/[0.03]",
            )}
          >
            <Icon
              size={15}
              className={clsx("mt-0.5 shrink-0", failed ? "text-red-400" : "text-slate-500")}
            />
            <div className="min-w-0 flex-1">
              <p className={clsx(failed ? "text-red-300" : "text-slate-200")}>{event.title}</p>
              {event.detail && (
                <p className="mt-0.5 text-xs text-slate-500">{event.detail}</p>
              )}
              {created && created.length > 0 && (
                <p className="mono mt-0.5 text-xs text-emerald-400">
                  + {created.join(", ")}
                </p>
              )}
              {failed && stderr && (
                <pre className="mono mt-1 max-h-24 overflow-auto rounded bg-black/50 p-2 text-[11px] text-red-300">
                  {stderr.trim().split("\n").slice(-6).join("\n")}
                </pre>
              )}
            </div>
            <span className="mono shrink-0 text-[11px] text-slate-600">
              {event.ts ? new Date(event.ts).toLocaleTimeString() : ""}
            </span>
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}
