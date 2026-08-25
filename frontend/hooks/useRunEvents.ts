"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { Arm, RunEvent } from "@/lib/types";

/** Subscribes to an experiment's SSE stream.
 *  The backend replays persisted history before attaching to live updates, so a
 *  late mount or a reconnect still yields the complete timeline. */
export function useRunEvents(experimentId: string | null, enabled = true) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const seen = useRef(new Set<string>());

  useEffect(() => {
    if (!experimentId || !enabled) return;

    seen.current.clear();
    setEvents([]);

    const source = new EventSource(`/api/experiments/${experimentId}/events`);

    source.onopen = () => setConnected(true);

    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as RunEvent & { kind: string };
        if (event.kind === "stream_end") {
          source.close();
          setConnected(false);
          return;
        }
        const key = `${event.run_id}:${event.seq}`;
        if (seen.current.has(key)) return;
        seen.current.add(key);
        setEvents((prev) => [...prev, event]);
      } catch {
        /* ignore malformed frame */
      }
    };

    source.onerror = () => {
      setConnected(false);
      // EventSource reconnects on its own; replay-then-subscribe makes that safe.
    };

    return () => source.close();
  }, [experimentId, enabled]);

  const byArm = useMemo(() => {
    const grouped: Record<Arm, RunEvent[]> = { base: [], skill: [] };
    for (const e of events) {
      if (e.arm === "base" || e.arm === "skill") grouped[e.arm].push(e);
    }
    return grouped;
  }, [events]);

  return { events, connected, byArm };
}
