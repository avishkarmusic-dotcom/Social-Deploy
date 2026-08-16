"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import {
  BarChart3, Command, Inbox, Moon, PenLine, Search, Settings, Sparkles, Sun,
  Users, Workflow, Zap,
} from "lucide-react";
import { Mono } from "@/components/ui/primitives";
import { Assistant } from "./Assistant";
import { CommandPalette } from "./CommandPalette";

const NAV = [
  { href: "/", label: "Command", Icon: Zap },
  { href: "/inbox", label: "Inbox", Icon: Inbox },
  { href: "/studio", label: "Studio", Icon: PenLine },
  { href: "/people", label: "People", Icon: Users },
  { href: "/rules", label: "Rules", Icon: Workflow },
  { href: "/data", label: "Data", Icon: BarChart3 },
];

export function Shell({ children }: { children: ReactNode }) {
  const [dark, setDark] = useState(true);
  const [assistant, setAssistant] = useState(false);
  const [palette, setPalette] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.classList.toggle("light", !dark);
  }, [dark]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      }
      if (e.key === "Escape") setPalette(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-dvh w-full flex-col overflow-hidden lg:flex-row">
      <nav
        className="hidden w-[60px] shrink-0 flex-col items-center gap-1 border-r border-line bg-panel py-4 lg:flex"
        aria-label="Sections"
      >
        <div className="mb-4 flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-iris to-mint">
          <span className="text-[13px] font-bold text-white">T</span>
        </div>
        {NAV.map(({ href, label, Icon }) => (
          <Link
            key={href}
            href={href}
            title={label}
            className={clsx(
              "flex h-10 w-10 items-center justify-center rounded-lg transition-all",
              pathname === href ? "bg-raise text-iris" : "text-faint hover:text-quiet",
            )}
          >
            <Icon size={17} />
          </Link>
        ))}
        <div className="mt-auto flex flex-col gap-1">
          <button
            onClick={() => setDark(!dark)}
            className="flex h-10 w-10 items-center justify-center rounded-lg text-faint hover:text-quiet"
            aria-label={dark ? "Switch to light" : "Switch to dark"}
          >
            {dark ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <Link
            href="/settings"
            className="flex h-10 w-10 items-center justify-center rounded-lg text-faint hover:text-quiet"
            aria-label="Settings"
          >
            <Settings size={16} />
          </Link>
        </div>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center gap-3 border-b border-line bg-panel px-4 py-3 lg:px-5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-iris to-mint lg:hidden">
            <span className="text-[11px] font-bold text-white">T</span>
          </div>
          <button
            onClick={() => setPalette(true)}
            className="flex max-w-sm flex-1 items-center gap-2.5 rounded-lg border border-line bg-raise px-3 py-1.5"
          >
            <Search size={13} className="text-faint" />
            <span className="text-[13px] text-faint">Search everything</span>
            <Mono className="ml-auto hidden items-center gap-0.5 text-faint sm:flex">
              <Command size={9} />K
            </Mono>
          </button>
          <button
            onClick={() => setDark(!dark)}
            className="p-2 text-faint lg:hidden"
            aria-label="Toggle theme"
          >
            {dark ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button
            onClick={() => setAssistant((a) => !a)}
            className={clsx(
              "flex items-center gap-1.5 rounded-lg border border-iris/30 px-3 py-1.5 text-[13px] transition-colors",
              assistant ? "bg-iris text-white" : "bg-iris/10 text-iris",
            )}
          >
            <Sparkles size={13} />
            <span className="hidden sm:inline">Ask</span>
          </button>
        </header>

        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1">{children}</div>
          {assistant && (
            <div className="hidden lg:flex">
              <Assistant onClose={() => setAssistant(false)} />
            </div>
          )}
        </div>

        <nav
          className="flex shrink-0 border-t border-line bg-panel lg:hidden"
          aria-label="Sections"
        >
          {NAV.map(({ href, label, Icon }) => (
            <Link
              key={href}
              href={href}
              className={clsx(
                "flex flex-1 flex-col items-center gap-1 py-2.5",
                pathname === href ? "text-iris" : "text-faint",
              )}
            >
              <Icon size={17} />
              <span className="font-mono text-[8px] uppercase tracking-wider">{label}</span>
            </Link>
          ))}
        </nav>
      </div>

      {assistant && (
        <div className="fixed inset-0 z-40 flex flex-col bg-ink lg:hidden">
          <Assistant onClose={() => setAssistant(false)} />
        </div>
      )}
      {palette && <CommandPalette onClose={() => setPalette(false)} />}
    </div>
  );
}
