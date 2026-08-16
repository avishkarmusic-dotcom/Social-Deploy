"use client";

import { useCallback, useState } from "react";
import {
  Copy, Hash, Loader2, PenLine, RefreshCw, Send,
  Sparkles, Clock, Check,
} from "lucide-react";
import { api, ApiFailure } from "@/lib/api";
import type { ContentKind, ContentVariant, SourceAccount } from "@/lib/types";
import { Button, Chip, Empty, Failure, Mono } from "@/components/ui/primitives";

/* ── Format catalogue ────────────────────────────────────────────────── */
const FORMATS: { id: ContentKind; label: string; hint: string }[] = [
  { id: "linkedin_post",     label: "LinkedIn post",     hint: "150–250 words, one idea" },
  { id: "x_thread",          label: "X thread",          hint: "5–8 posts, first post stands alone" },
  { id: "instagram_caption", label: "Instagram caption", hint: "Under 125 words before the fold" },
  { id: "facebook_post",     label: "Facebook post",     hint: "80–150 words, conversational" },
  { id: "newsletter",        label: "Newsletter intro",  hint: "Open with the single most useful sentence" },
  { id: "email_campaign",    label: "Email campaign",    hint: "Under 150 words, one clear CTA" },
  { id: "blog_article",      label: "Blog article",      hint: "700–1000 words with subheadings" },
  { id: "product_launch",    label: "Product launch",    hint: "What it does, who it's for, what changed" },
  { id: "hashtags",          label: "Hashtags",          hint: "8–15, mixed reach" },
  { id: "seo_title",         label: "SEO title",         hint: "Under 60 characters" },
  { id: "meta_description",  label: "Meta description",  hint: "150–158 characters" },
];

const TONES = ["confident", "casual", "professional", "founder", "sales"];

/* ── Variant card ────────────────────────────────────────────────────── */
function VariantCard({
  variant,
  index,
  onSchedule,
}: {
  variant: ContentVariant;
  index: number;
  onSchedule: (body: string) => void;
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(variant.body);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <article
      className="flex flex-col rounded-xl border border-line bg-raise p-4"
      style={{ animation: `rise 400ms ease ${index * 80}ms both` }}
    >
      <div className="mb-3 flex items-center gap-2">
        <Mono className="text-iris">0{index + 1}</Mono>
        <span className="text-[13px] font-medium text-paper">{variant.angle}</span>
      </div>

      <p className="flex-1 whitespace-pre-wrap text-[13px] leading-relaxed text-quiet">
        {variant.body}
      </p>

      {variant.hashtags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {variant.hashtags.map((h) => (
            <Mono key={h} className="text-mint">
              {h.startsWith("#") ? h : `#${h}`}
            </Mono>
          ))}
        </div>
      )}

      <div className="mt-4 flex gap-2 border-t border-line pt-3">
        <Button primary small onClick={() => onSchedule(variant.body)}>
          <span className="flex items-center gap-1.5">
            <Clock size={12} /> Save draft
          </span>
        </Button>
        <Button small onClick={copy}>
          <span className="flex items-center gap-1.5">
            {copied ? <Check size={12} className="text-mint" /> : <Copy size={12} />}
            {copied ? "Copied" : "Copy"}
          </span>
        </Button>
      </div>
    </article>
  );
}

/* ── Page ────────────────────────────────────────────────────────────── */
export default function StudioPage() {
  const [format, setFormat] = useState<ContentKind>("linkedin_post");
  const [tone, setTone] = useState("confident");
  const [brief, setBrief] = useState("");
  const [variants, setVariants] = useState<ContentVariant[]>([]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const generate = useCallback(async () => {
    if (!brief.trim()) return;
    setBusy(true);
    setFailure(null);
    setVariants([]);
    setSaved(null);
    try {
      const result = await api.ai.content({ kind: format, brief, tone, variants: 3 });
      setVariants(result);
    } catch (e) {
      if (e instanceof ApiFailure) setFailure(e);
    } finally {
      setBusy(false);
    }
  }, [brief, format, tone]);

  const saveDraft = async (body: string) => {
    try {
      await api.content.create({ kind: format, body });
      setSaved(body.slice(0, 40));
    } catch { /* silent — draft saved is not critical path */ }
  };

  const hint = FORMATS.find((f) => f.id === format)?.hint ?? "";

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 lg:px-8">
      <h1 className="mb-1 text-xl font-semibold tracking-tight text-paper">
        Content Studio
      </h1>
      <p className="mb-6 text-sm text-quiet">
        One brief. Three different angles. Pick the one that fits.
      </p>

      {/* Format picker */}
      <div className="mb-4 flex flex-wrap gap-1.5">
        {FORMATS.map((f) => (
          <Chip
            key={f.id}
            tone="iris"
            active={format === f.id}
            onClick={() => setFormat(f.id)}
          >
            {f.label}
          </Chip>
        ))}
      </div>

      {/* Tone picker */}
      <div className="mb-4 flex gap-1.5">
        {TONES.map((t) => (
          <Chip key={t} tone="quiet" active={tone === t} onClick={() => setTone(t)}>
            {t}
          </Chip>
        ))}
      </div>

      {/* Brief input */}
      <div className="mb-6 overflow-hidden rounded-xl border border-line bg-raise">
        <textarea
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void generate();
          }}
          placeholder="What happened this week that's worth telling people about?"
          rows={3}
          className="w-full resize-none bg-transparent px-4 py-3 text-[14px] text-paper outline-none placeholder:text-faint"
          aria-label="Content brief"
        />
        <div
          className="flex items-center gap-3 border-t border-line px-3 py-2.5"
        >
          <Button primary small onClick={generate} disabled={busy || !brief.trim()}>
            <span className="flex items-center gap-1.5">
              {busy ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Sparkles size={13} />
              )}
              {busy ? "Writing…" : "Write three versions"}
            </span>
          </Button>
          <Mono className="text-faint">{hint}</Mono>
          <Mono className="ml-auto hidden text-faint sm:block">⌘↵</Mono>
        </div>
      </div>

      {failure && (
        <div className="mb-6">
          <Failure message={failure.message} fix={failure.fix} />
        </div>
      )}

      {saved && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-mint/25 bg-mint/[0.06] px-3 py-2">
          <Check size={13} className="text-mint" />
          <span className="text-[13px] text-quiet">
            Saved draft: <span className="text-paper">"{saved}…"</span>
          </span>
        </div>
      )}

      {busy && !variants.length && (
        <div className="flex items-center justify-center gap-2 py-16">
          <Loader2 size={14} className="animate-spin text-iris" />
          <Mono className="text-iris">Drafting three angles…</Mono>
        </div>
      )}

      {variants.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-3">
          {variants.map((v, i) => (
            <VariantCard key={i} variant={v} index={i} onSchedule={saveDraft} />
          ))}
        </div>
      )}

      {!busy && variants.length === 0 && !failure && (
        <Empty
          icon={<PenLine size={24} />}
          title="Describe the week and it'll find the angle. Nothing is scheduled until you pick one."
        />
      )}
    </div>
  );
}
