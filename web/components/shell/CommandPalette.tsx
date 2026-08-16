"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronRight, Search } from "lucide-react";
import { api } from "@/lib/api";
import { Mono } from "@/components/ui/primitives";

const DESTINATIONS = [
  { label: "Go to Command", href: "/" },
  { label: "Go to Inbox", href: "/inbox" },
  { label: "Go to Studio", href: "/studio" },
  { label: "Go to People", href: "/people" },
  { label: "Go to Rules", href: "/rules" },
  { label: "Go to Data", href: "/data" },
];

export function CommandPalette({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<{ id: string; kind: string; title: string }[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const router = useRouter();

  useEffect(() => input.current?.focus(), []);

  // Debounced so typing doesn't fire a search per keystroke.
  useEffect(() => {
    if (query.length < 2) {
      setHits([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const result = await api.search(query);
        setHits(result.hits as never[]);
      } catch {
        setHits([]);
      }
    }, 180);
    return () => clearTimeout(timer);
  }, [query]);

  const destinations = DESTINATIONS.filter((d) =>
    d.label.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/55 px-4 pt-[12vh] backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Search and navigate"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg animate-rise overflow-hidden rounded-xl border border-line bg-raise shadow-2xl"
      >
        <div className="flex items-center gap-3 border-b border-line px-4 py-3.5">
          <Search size={15} className="text-faint" />
          <input
            ref={input}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && onClose()}
            placeholder="Search everything, or jump somewhere"
            className="flex-1 bg-transparent text-sm text-paper outline-none placeholder:text-faint"
          />
          <Mono className="text-faint">esc</Mono>
        </div>

        <div className="max-h-80 overflow-y-auto py-2">
          {destinations.length > 0 && (
            <Mono className="block px-4 py-1 text-faint">Navigate</Mono>
          )}
          {destinations.map((d) => (
            <button
              key={d.href}
              onClick={() => {
                router.push(d.href);
                onClose();
              }}
              className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-[13px] text-paper hover:bg-panel"
            >
              <ChevronRight size={13} className="text-faint" />
              {d.label}
            </button>
          ))}

          {hits.length > 0 && <Mono className="mt-1 block px-4 py-1 text-faint">Results</Mono>}
          {hits.map((h) => (
            <button
              key={`${h.kind}-${h.id}`}
              onClick={() => {
                if (h.kind === "thread") router.push(`/inbox?thread=${h.id}`);
                onClose();
              }}
              className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-panel"
            >
              <Mono className="w-14 shrink-0 text-faint">{h.kind}</Mono>
              <span className="flex-1 truncate text-[13px] text-paper">{h.title}</span>
            </button>
          ))}

          {query.length >= 2 && hits.length === 0 && destinations.length === 0 && (
            <p className="px-4 py-8 text-center text-[13px] text-quiet">
              Nothing matches “{query}”. Try a person&apos;s name or a phrase from a message.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
