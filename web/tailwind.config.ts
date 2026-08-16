import type { Config } from "tailwindcss";

/**
 * Colours are CSS variables, not literals, so the theme switch is a class on
 * <html> rather than a re-render of every component that knows a hex value.
 */
export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "rgb(var(--ink) / <alpha-value>)",
        panel: "rgb(var(--panel) / <alpha-value>)",
        raise: "rgb(var(--raise) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        "line-soft": "rgb(var(--line-soft) / <alpha-value>)",
        paper: "rgb(var(--paper) / <alpha-value>)",
        quiet: "rgb(var(--quiet) / <alpha-value>)",
        faint: "rgb(var(--faint) / <alpha-value>)",
        mint: "rgb(var(--mint) / <alpha-value>)",
        iris: "rgb(var(--iris) / <alpha-value>)",
        ember: "rgb(var(--ember) / <alpha-value>)",
        amber: "rgb(var(--amber) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
      fontSize: {
        micro: ["0.625rem", { lineHeight: "0.875rem", letterSpacing: "0.08em" }],
      },
      keyframes: {
        rise: {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "none" },
        },
        fill: { from: { height: "0%" } },
      },
      animation: {
        rise: "rise 420ms cubic-bezier(.2,.7,.3,1) both",
        fill: "fill 600ms cubic-bezier(.2,.7,.3,1) both",
      },
    },
  },
  plugins: [],
} satisfies Config;
