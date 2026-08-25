import { Badge } from "./Badge";
import { Spinner } from "./Spinner";

const TONE: Record<string, "neutral" | "good" | "warn" | "bad" | "info"> = {
  pending: "neutral", queued: "neutral",
  parsing: "info", parsed: "info", extracting: "info",
  running: "info", evaluating: "info",
  extracted: "good", completed: "good",
  failed: "bad", cancelled: "warn", uploaded: "neutral",
};

const BUSY = new Set(["running", "evaluating", "parsing", "extracting"]);

export function StatusPill({ status }: { status: string }) {
  return (
    <Badge tone={TONE[status] ?? "neutral"}>
      <span className="inline-flex items-center gap-1.5">
        {BUSY.has(status) && <Spinner className="h-3 w-3" />}
        {status}
      </span>
    </Badge>
  );
}
