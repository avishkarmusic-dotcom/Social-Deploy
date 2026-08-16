"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, ExternalLink, Loader2,
         Plus, RefreshCw, Trash2, Unplug, Wifi } from "lucide-react";
import clsx from "clsx";
import { api, ApiFailure } from "@/lib/api";
import type { SourceAccount } from "@/lib/types";
import { channel } from "@/lib/channels";
import { relativeTime } from "@/lib/format";
import { Button, Chip, Empty, Failure, Mono } from "@/components/ui/primitives";

/* ── Available sources (from /v1/meta) ────────────────────────────────── */
interface AvailableSource {
  kind: string;
  configured: boolean;
}

/* ── Source card ─────────────────────────────────────────────────────── */
function SourceCard({
  account,
  onSync,
  onDisconnect,
}: {
  account: SourceAccount;
  onSync: () => void;
  onDisconnect: () => void;
}) {
  const { Icon, hue, label } = channel(account.source_kind);
  const ok = account.status === "connected";

  return (
    <div className="flex items-center gap-3 rounded-xl border border-line bg-raise px-4 py-3.5">
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
        style={{ background: `${hue}18` }}
      >
        <Icon size={17} style={{ color: hue }} aria-label={label} />
      </div>

      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-paper">{account.display_name}</p>
        <div className="flex items-center gap-1.5">
          {ok ? (
            <CheckCircle2 size={11} className="text-mint" />
          ) : (
            <AlertCircle size={11} className="text-ember" />
          )}
          <Mono className={ok ? "text-mint" : "text-ember"}>{account.status}</Mono>
          {account.last_synced_at && (
            <Mono className="text-faint">
              · synced {relativeTime(account.last_synced_at)}
            </Mono>
          )}
        </div>
        {account.last_error && (
          <p className="mt-0.5 text-[11px] text-ember">{account.last_error}</p>
        )}
      </div>

      <div className="flex shrink-0 gap-1">
        <button
          onClick={onSync}
          className="rounded-md p-1.5 text-faint hover:text-paper"
          aria-label="Sync now"
          title="Sync now"
        >
          <RefreshCw size={14} />
        </button>
        <button
          onClick={onDisconnect}
          className="rounded-md p-1.5 text-faint hover:text-ember"
          aria-label="Disconnect"
          title="Disconnect"
        >
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  );
}

/* ── Connect modal ────────────────────────────────────────────────────── */
function ConnectPanel({
  available,
  connected,
  onConnect,
}: {
  available: AvailableSource[];
  connected: SourceAccount[];
  onConnect: (kind: string) => void;
}) {
  const connectedKinds = new Set(connected.map((a) => a.source_kind));
  const toAdd = available.filter((s) => !connectedKinds.has(s.kind));

  if (toAdd.length === 0) {
    return (
      <p className="text-sm text-quiet">
        All available sources are connected.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
      {toAdd.map((s) => {
        const { Icon, hue, label } = channel(s.kind);
        return (
          <button
            key={s.kind}
            onClick={() => onConnect(s.kind)}
            disabled={!s.configured}
            title={!s.configured ? "Not configured in this deployment" : undefined}
            className={clsx(
              "flex flex-col items-center gap-2 rounded-xl border py-4 transition-all",
              s.configured
                ? "border-line bg-raise hover:border-iris/40"
                : "cursor-not-allowed border-line bg-raise opacity-35",
            )}
          >
            <Icon size={20} style={{ color: hue }} />
            <Mono className="text-quiet">{label}</Mono>
          </button>
        );
      })}
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────── */
export default function SettingsPage() {
  const [accounts, setAccounts]   = useState<SourceAccount[]>([]);
  const [available, setAvailable] = useState<AvailableSource[]>([]);
  const [loading, setLoading]     = useState(true);
  const [adding, setAdding]       = useState(false);
  const [failure, setFailure]     = useState<ApiFailure | null>(null);
  const [syncing, setSyncing]     = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [accs, meta] = await Promise.all([
        api.sources.list(),
        api.sources.meta(),
      ]);
      setAccounts(accs);
      setAvailable(meta.channels);
    } catch (e) {
      if (e instanceof ApiFailure) setFailure(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const connect = async (kind: string) => {
    try {
      const { authorize_url } = await api.sources.connect(kind);
      window.location.href = authorize_url;
    } catch (e) {
      if (e instanceof ApiFailure) setFailure(e);
    }
  };

  const sync = async (id: string) => {
    setSyncing(id);
    try {
      await api.sources.sync(id);
    } finally {
      setSyncing(null);
    }
  };

  const disconnect = async (id: string) => {
    if (!confirm("Disconnect this source? Messages already imported stay in the inbox.")) return;
    try {
      await api.sources.disconnect(id);
      setAccounts((prev) => prev.filter((a) => a.id !== id));
    } catch (e) {
      if (e instanceof ApiFailure) setFailure(e);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 lg:px-8">
      <h1 className="mb-1 text-xl font-semibold tracking-tight text-paper">Settings</h1>
      <p className="mb-6 text-sm text-quiet">Manage connected sources and workspace preferences.</p>

      {failure && (
        <div className="mb-6">
          <Failure message={failure.message} fix={failure.fix} />
        </div>
      )}

      {/* Connected sources */}
      <section className="mb-8">
        <div className="mb-3 flex items-center justify-between">
          <Mono className="text-faint">Connected sources</Mono>
          <Button small primary onClick={() => setAdding((a) => !a)}>
            <span className="flex items-center gap-1.5">
              <Plus size={13} /> Add source
            </span>
          </Button>
        </div>

        {loading && (
          <div className="flex justify-center py-8">
            <Loader2 size={16} className="animate-spin text-faint" />
          </div>
        )}

        {!loading && accounts.length === 0 && !failure && (
          <Empty
            icon={<Wifi size={22} />}
            title="No sources connected yet. Add one and your inbox starts filling."
            action={
              <Button primary onClick={() => setAdding(true)}>
                Connect your first source
              </Button>
            }
          />
        )}

        <div className="space-y-2">
          {accounts.map((account) => (
            <SourceCard
              key={account.id}
              account={{ ...account, source_kind: account.source_kind }}
              onSync={() => void sync(account.id)}
              onDisconnect={() => void disconnect(account.id)}
            />
          ))}
        </div>
      </section>

      {/* Add source panel */}
      {adding && (
        <section className="mb-8 rounded-xl border border-iris/25 bg-raise p-5">
          <Mono className="mb-4 text-iris">Choose a source to connect</Mono>
          <ConnectPanel
            available={available}
            connected={accounts}
            onConnect={connect}
          />
        </section>
      )}

      {/* Workspace section */}
      <section>
        <Mono className="mb-3 text-faint">Workspace</Mono>
        <div className="space-y-2 rounded-xl border border-line bg-raise">
          {[
            ["Plan", "Pro"],
            ["AI budget (today)", "tracking"],
            ["Automations", "active"],
          ].map(([label, value]) => (
            <div
              key={label}
              className="flex items-center justify-between px-4 py-3 border-b border-line last:border-0"
            >
              <span className="text-[13px] text-quiet">{label}</span>
              <Mono className="text-paper">{value}</Mono>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
