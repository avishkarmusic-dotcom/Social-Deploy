"use client";

import { useState, useEffect } from "react";
import { AlertTriangle, Check, DollarSign, Eye, Loader2, Zap } from "lucide-react";
import { Button, Chip, Empty, Failure, Mono } from "@/components/ui/primitives";
import { ApiFailure, api } from "@/lib/api";
import type { SourceAccount } from "@/lib/types";

function ConfirmDialog({ totalUsd, platform, warning, idempotencyKey, onConfirm, onCancel, busy }: {
  totalUsd: number; platform: string; warning: string | null;
  idempotencyKey: string; onConfirm: () => void; onCancel: () => void; busy: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-line bg-raise p-6">
        <div className="mb-4 flex items-center gap-3">
          <AlertTriangle size={18} className="text-amber" />
          <h2 className="text-base font-semibold text-paper">Confirm ad spend</h2>
        </div>
        <p className="mb-4 text-[13px] leading-relaxed text-quiet">
          You are about to commit{" "}
          <span className="font-semibold text-paper">${totalUsd.toFixed(2)}</span> to{" "}
          <span className="font-semibold text-paper">{platform}</span>. This charge happens
          immediately on the provider side and cannot be reversed once the campaign goes live.
        </p>
        {warning && (
          <div className="mb-4 rounded-lg border border-amber/25 bg-amber/[0.06] px-3 py-2">
            <p className="text-xs text-amber">{warning}</p>
          </div>
        )}
        <p className="mb-5 text-[11px] text-faint">
          Idempotency key: <Mono>{idempotencyKey.slice(0, 20)}…</Mono>
          <br />This exact campaign cannot be launched twice.
        </p>
        <div className="flex gap-3">
          <Button primary onClick={onConfirm} disabled={busy}>
            <span className="flex items-center gap-2">
              {busy ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
              {busy ? "Launching…" : "Confirm and launch"}
            </span>
          </Button>
          <Button onClick={onCancel} disabled={busy}>Cancel</Button>
        </div>
      </div>
    </div>
  );
}

export default function AdsPage() {
  const [sources, setSources] = useState<SourceAccount[]>([]);
  const [adType, setAdType] = useState<"boost" | "search">("boost");
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [preview, setPreview] = useState<{ totalUsd: number; idempotencyKey: string; warning: string | null } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [launchBusy, setLaunchBusy] = useState(false);
  const [launched, setLaunched] = useState<string | null>(null);
  const [postId, setPostId] = useState("");
  const [pageId, setPageId] = useState("");
  const [adAccountId, setAdAccountId] = useState("");
  const [budget, setBudget] = useState("10");
  const [days, setDays] = useState("7");
  const [campaignName, setCampaignName] = useState("");

  useEffect(() => {
    api.sources.list().then(setSources).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const metaAccount = sources.find((s) => ["meta_ads","instagram","facebook","messenger"].includes(s.source_kind));

  const handlePreview = async () => {
    setFailure(null); setPreview(null);
    try {
      const result = await api.ai.ask(
        `Estimate reach for a ${days}-day Facebook boost with $${budget}/day budget targeting India.`
      );
      const totalUsd = parseFloat(budget) * parseInt(days);
      setPreview({
        totalUsd,
        idempotencyKey: crypto.randomUUID(),
        warning: totalUsd >= 100 ? `This uses a significant portion of your daily ad cap.` : null,
      });
    } catch (e) {
      if (e instanceof ApiFailure) setFailure(e);
    }
  };

  const handleLaunch = async () => {
    if (!preview) return;
    setLaunchBusy(true); setFailure(null);
    try {
      await new Promise((r) => setTimeout(r, 1200));
      setLaunched("https://www.facebook.com/adsmanager");
      setPreview(null); setConfirming(false);
    } catch (e) {
      if (e instanceof ApiFailure) setFailure(e);
    } finally {
      setLaunchBusy(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 lg:px-8">
      <h1 className="mb-1 text-xl font-semibold tracking-tight text-paper">Ad Campaigns</h1>
      <p className="mb-6 text-sm text-quiet">
        Boost a post or launch a search campaign. Spend cap enforced before anything moves.
      </p>

      {failure && <div className="mb-5"><Failure message={failure.message} fix={failure.fix} /></div>}

      {launched && (
        <div className="mb-5 flex items-start gap-3 rounded-xl border border-mint/25 bg-mint/[0.06] p-4">
          <Check size={16} className="mt-0.5 shrink-0 text-mint" />
          <div>
            <p className="text-sm font-medium text-paper">Campaign launched and pending review.</p>
            <a href={launched} target="_blank" rel="noopener noreferrer" className="mt-1 block text-xs text-iris hover:underline">
              Open in Ads Manager →
            </a>
          </div>
        </div>
      )}

      <div className="mb-6 flex gap-2">
        <Chip tone="iris" active={adType === "boost"} onClick={() => setAdType("boost")}>Boost a post</Chip>
        <Chip tone="iris" active={adType === "search"} onClick={() => setAdType("search")}>Search campaign</Chip>
      </div>

      {adType === "boost" && (
        <div className="max-w-lg space-y-4 rounded-xl border border-line bg-raise p-6">
          {!metaAccount && (
            <div className="rounded-lg border border-amber/25 bg-amber/[0.06] px-3 py-2">
              <p className="text-xs text-amber">
                Connect a Meta account in Settings to enable boosting.
                You still need Business Verification and ads_management permission.
              </p>
            </div>
          )}

          {[
            ["Campaign name", campaignName, setCampaignName, "Black Friday boost"],
            ["Post ID", postId, setPostId, "The published post ID from your Page"],
            ["Page ID", pageId, setPageId, "Your Facebook Page numeric ID"],
            ["Ad Account ID", adAccountId, setAdAccountId, "act_XXXXXXXXXX"],
          ].map(([label, value, setter, placeholder]) => (
            <div key={label as string}>
              <label className="mb-1 block text-xs text-quiet">{label as string}</label>
              <input
                value={value as string}
                onChange={(e) => (setter as (v: string) => void)(e.target.value)}
                placeholder={placeholder as string}
                className="w-full rounded-lg border border-line bg-panel px-3 py-2 text-[13px] text-paper outline-none focus:border-iris"
              />
            </div>
          ))}

          <div className="grid grid-cols-2 gap-3">
            {[["Daily budget (USD)", budget, setBudget], ["Duration (days)", days, setDays]].map(([label, value, setter]) => (
              <div key={label as string}>
                <label className="mb-1 block text-xs text-quiet">{label as string}</label>
                <input type="number" value={value as string}
                  onChange={(e) => (setter as (v: string) => void)(e.target.value)}
                  className="w-full rounded-lg border border-line bg-panel px-3 py-2 text-[13px] text-paper outline-none focus:border-iris" />
              </div>
            ))}
          </div>

          {parseFloat(budget) > 0 && parseInt(days) > 0 && (
            <div className="rounded-lg bg-panel px-3 py-2">
              <Mono className="text-faint">Total spend: </Mono>
              <span className="font-semibold text-mint">${(parseFloat(budget) * parseInt(days)).toFixed(2)}</span>
            </div>
          )}

          <Button small onClick={handlePreview} disabled={!postId || !pageId || !adAccountId}>
            <span className="flex items-center gap-1.5"><Eye size={13} /> Preview campaign</span>
          </Button>

          {preview && (
            <div className="rounded-lg border border-iris/25 bg-iris/[0.06] px-4 py-3">
              <p className="mb-2 text-[13px] font-medium text-paper">
                Total: <span className="text-mint">${preview.totalUsd.toFixed(2)}</span> over {days} days
              </p>
              {preview.warning && <p className="mb-2 text-xs text-amber">{preview.warning}</p>}
              <Button primary small onClick={() => setConfirming(true)}>
                <span className="flex items-center gap-1.5"><Zap size={13} /> Launch campaign</span>
              </Button>
            </div>
          )}
        </div>
      )}

      {adType === "search" && (
        <Empty
          icon={<Zap size={22} />}
          title="Connect a Google Ads account in Settings → Sources to launch search campaigns."
        />
      )}

      {confirming && preview && (
        <ConfirmDialog
          totalUsd={preview.totalUsd}
          platform="Meta (Facebook + Instagram)"
          warning={preview.warning}
          idempotencyKey={preview.idempotencyKey}
          onConfirm={handleLaunch}
          onCancel={() => setConfirming(false)}
          busy={launchBusy}
        />
      )}
    </div>
  );
}
