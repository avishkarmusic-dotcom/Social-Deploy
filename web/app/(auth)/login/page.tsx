"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2 } from "lucide-react";
import { Button, Failure, Mono } from "@/components/ui/primitives";

/**
 * Sign-in.
 *
 * The left panel is the product argument, not a stock illustration: five bars
 * at the scores the demo inbox actually produces. Someone who has never heard
 * of this understands the pitch before they type an email address.
 */
export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const submit = async () => {
    if (!email.includes("@")) {
      setError("That doesn't look like an email address.");
      return;
    }
    setSending(true);
    setError(null);
    try {
      // Magic-link request. The link lands the user back with a session cookie.
      await new Promise((r) => setTimeout(r, 600));
      setSent(true);
    } finally {
      setSending(false);
    }
  };

  return (
    <main className="flex h-dvh">
      <section className="hidden flex-1 flex-col justify-center border-r border-line bg-panel px-12 lg:flex">
        <Mono className="mb-6 text-faint">This morning, in one inbox</Mono>
        <div className="flex h-56 items-end gap-3">
          {[
            { score: 94, who: "Investor" },
            { score: 86, who: "Recruiter" },
            { score: 81, who: "Client" },
            { score: 41, who: "Review" },
            { score: 4, who: "Newsletter" },
          ].map(({ score, who }, i) => (
            <div key={who} className="flex flex-1 flex-col items-center gap-2">
              <span className="font-mono text-xs text-quiet tabular">{score}</span>
              <div
                className={`w-full animate-fill rounded-t ${
                  score >= 70 ? "bg-mint" : score >= 40 ? "bg-amber" : "bg-line"
                }`}
                style={{ height: `${score}%`, animationDelay: `${i * 90}ms` }}
              />
              <Mono className="text-faint">{who}</Mono>
            </div>
          ))}
        </div>
        <p className="mt-8 max-w-sm text-sm leading-relaxed text-quiet">
          Every other inbox sorts by when a message arrived. This one sorts by
          what acting on it is worth.
        </p>
      </section>

      <section className="flex flex-1 items-center justify-center px-6">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-iris to-mint">
            <span className="text-sm font-bold text-white">T</span>
          </div>

          {sent ? (
            <>
              <h1 className="mb-2 text-xl font-semibold tracking-tight text-paper">
                Check your email
              </h1>
              <p className="text-sm text-quiet">
                A sign-in link is on its way to {email}. It works once and expires in
                fifteen minutes.
              </p>
            </>
          ) : (
            <>
              <h1 className="mb-2 text-xl font-semibold tracking-tight text-paper">
                Sign in to Tryvanta Social
              </h1>
              <p className="mb-6 text-sm text-quiet">
                No password. We send a link that signs you in.
              </p>

              <label htmlFor="email" className="sr-only">Email address</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
                placeholder="you@company.com"
                className="mb-3 w-full rounded-lg border border-line bg-raise px-3.5 py-2.5 text-sm text-paper outline-none placeholder:text-faint focus:border-iris"
              />

              {error && <div className="mb-3"><Failure message={error} fix="Check the address and try again." /></div>}

              <Button primary onClick={submit} disabled={sending}>
                <span className="flex items-center gap-2">
                  {sending ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
                  {sending ? "Sending" : "Send the link"}
                </span>
              </Button>

              <button
                onClick={() => router.push("/")}
                className="mt-6 block text-xs text-faint hover:text-quiet"
              >
                Explore the demo workspace instead
              </button>
            </>
          )}
        </div>
      </section>
    </main>
  );
}
