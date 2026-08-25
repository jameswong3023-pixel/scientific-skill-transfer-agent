"use client";

import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";

import { Panel } from "@/components/ui/Panel";
import { Spinner } from "@/components/ui/Spinner";
import { api } from "@/lib/api";
import type { Message, ViewDirective } from "@/lib/types";

const SUGGESTIONS = [
  "What technique did you extract from this paper?",
  "Why did the first segmentation fail?",
  "Show me slice 32.",
  "What parameters came from the paper?",
  "Which parts did you infer rather than extract?",
  "How was grey matter volume calculated?",
];

export function ChatPanel({
  experimentId,
  onShowSlice,
}: {
  experimentId: string;
  /** Applied when the agent calls `show_slice`, so an answer about a slice
   *  moves the images instead of only describing them. */
  onShowSlice?: (directive: ViewDirective) => void;
}) {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .createConversation(experimentId)
      .then((c) => setConversationId(c.id))
      .catch(() => setConversationId(null));
  }, [experimentId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, busy]);

  async function send(text: string) {
    if (!conversationId || !text.trim() || busy) return;
    setDraft("");
    setBusy(true);
    setMessages((prev) => [
      ...prev,
      {
        id: `local-${Date.now()}`, role: "user", content: text,
        tool_calls: {}, created_at: new Date().toISOString(),
      },
    ]);
    try {
      const reply = await api.sendMessage(conversationId, text);
      setMessages((prev) => [...prev, reply]);
      if (reply.tool_calls?.view) onShowSlice?.(reply.tool_calls.view);
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`, role: "assistant",
          content: `Sorry — I could not answer that (${String(e)}).`,
          tool_calls: {}, created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Ask the agent" subtitle="Grounded in this experiment's real record">
      <div className="mb-3 max-h-96 space-y-3 overflow-y-auto pr-1">
        {messages.length === 0 && (
          <div className="space-y-1.5">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => void send(s)}
                className="block w-full rounded-lg border border-[var(--border)] px-3 py-2 text-left text-sm text-slate-400 hover:border-violet-500/40 hover:text-slate-200"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={m.role === "user" ? "ml-8 rounded-lg bg-violet-600/20 p-3" : "mr-8 rounded-lg bg-white/[0.04] p-3"}
          >
            <p className="whitespace-pre-wrap text-sm text-slate-200">{m.content}</p>
            {m.tool_calls?.view && (
              <button
                onClick={() => onShowSlice?.(m.tool_calls.view!)}
                className="mt-1.5 text-[11px] text-violet-400 hover:text-violet-300"
              >
                ▲ moved the viewers to {m.tool_calls.view.axis ?? "this"} slice{" "}
                {m.tool_calls.view.index + 1} — click to go back
              </button>
            )}
            {m.tool_calls?.used && m.tool_calls.used.length > 0 && (
              <p className="mono mt-1.5 text-[11px] text-slate-500">
                looked up: {m.tool_calls.used.join(", ")}
              </p>
            )}
          </div>
        ))}
        {busy && (
          <div className="mr-8 flex items-center gap-2 rounded-lg bg-white/[0.04] p-3 text-sm text-slate-400">
            <Spinner /> checking the run record…
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void send(draft);
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask about the skill, the code, the failures, or the numbers…"
          disabled={!conversationId || busy}
          className="flex-1 rounded-lg border border-[var(--border)] bg-black/30 px-3 py-2 text-sm text-slate-100 outline-none focus:border-violet-500"
        />
        <button
          type="submit"
          disabled={!conversationId || busy || !draft.trim()}
          className="rounded-lg bg-violet-600 px-3 text-white disabled:opacity-40"
        >
          <Send size={16} />
        </button>
      </form>
    </Panel>
  );
}
