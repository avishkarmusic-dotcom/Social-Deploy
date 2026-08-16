"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Send, Sparkles, X } from "lucide-react";
import { api, ApiFailure } from "@/lib/api";
import { Mono } from "@/components/ui/primitives";

const STARTERS = [
  "What should I answer first today?",
  "Which relationships have gone cold?",
  "Summarise everything waiting on me.",
];

type Turn = { role: "you" | "assistant"; text: string };

export function Assistant({ onClose }: { onClose: () => void }) {
  const [log, setLog] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [thinking, setThinking] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [log, thinking]);

  const ask = async (text?: string) => {
    const q = (text ?? question).trim();
    if (!q || thinking) return;
    setLog((l) => [...l, { role: "you", text: q }]);
    setQuestion("");
    setThinking(true);
    try {
      const { answer } = await api.ai.ask(q);
      setLog((l) => [...l, { role: "assistant", text: answer }]);
    } catch (e) {
      const text =
        e instanceof ApiFailure ? `${e.message} ${e.fix}` : "That didn't come back. Ask again.";
      setLog((l) => [...l, { role: "assistant", text }]);
    } finally {
      setThinking(false);
    }
  };

  return (
    <aside className="flex w-full shrink-0 flex-col border-l border-line bg-panel lg:w-96">
      <header className="flex items-center gap-2 border-b border-line px-4 py-3.5">
        <Sparkles size={13} className="text-iris" />
        <Mono className="text-paper">Assistant</Mono>
        <button onClick={onClose} className="ml-auto p-1 text-faint hover:text-paper" aria-label="Close assistant">
          <X size={15} />
        </button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {log.length === 0 && (
          <div className="space-y-2">
            <p className="mb-3 text-[13px] text-quiet">
              Ask anything about what&apos;s in your inbox right now.
            </p>
            {STARTERS.map((s) => (
              <button
                key={s}
                onClick={() => ask(s)}
                className="w-full rounded-lg border border-line bg-raise px-3 py-2.5 text-left text-xs text-quiet transition-colors hover:text-paper"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {log.map((turn, i) => (
          <div
            key={i}
            className={
              turn.role === "you"
                ? "rounded-lg border border-line bg-raise px-3.5 py-2.5 text-[13px] leading-relaxed text-paper"
                : "glow rounded-lg border border-iris/25 px-3.5 py-2.5 text-[13px] leading-relaxed text-paper whitespace-pre-wrap"
            }
          >
            {turn.text}
          </div>
        ))}

        {thinking && (
          <div className="flex items-center gap-2 px-1">
            <Loader2 size={12} className="animate-spin text-iris" />
            <Mono className="text-iris">Reading your inbox…</Mono>
          </div>
        )}
        <div ref={bottom} />
      </div>

      <div className="border-t border-line p-3">
        <div className="flex gap-2 rounded-lg border border-line bg-raise px-3 py-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask()}
            placeholder="Ask about your inbox…"
            aria-label="Ask the assistant"
            className="flex-1 bg-transparent text-[13px] text-paper outline-none placeholder:text-faint"
          />
          <button
            onClick={() => ask()}
            disabled={thinking || !question.trim()}
            className="text-iris disabled:text-faint"
            aria-label="Send question"
          >
            <Send size={14} />
          </button>
        </div>
      </div>
    </aside>
  );
}
