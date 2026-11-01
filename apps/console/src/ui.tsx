// Small shared pieces: the logo, one icon set (16 px, 1.75 stroke), alerts, a copy button, a status pill.
import { useId, useState, type ReactNode } from "react";

const PATHS: Record<string, string> = {
  check: "M3.5 8.5l3 3 6-7",
  copy: "M5.5 5.5V3.25c0-.41.34-.75.75-.75h6.5c.41 0 .75.34.75.75v6.5c0 .41-.34.75-.75.75H10.5M3.25 5.5h6.5c.41 0 .75.34.75.75v6.5c0 .41-.34.75-.75.75h-6.5a.75.75 0 0 1-.75-.75v-6.5c0-.41.34-.75.75-.75z",
  upload: "M8 10.5V2.5M4.5 6 8 2.5 11.5 6M2.5 10.5v2.25c0 .41.34.75.75.75h9.5c.41 0 .75-.34.75-.75V10.5",
  external: "M9.5 2.5h4v4M13.5 2.5 7.5 8.5M11.5 9.5v3.25c0 .41-.34.75-.75.75h-7.5a.75.75 0 0 1-.75-.75v-7.5c0-.41.34-.75.75-.75H6.5",
  dot: "M8 8h.01",
  file: "M9 1.75H4.5a.75.75 0 0 0-.75.75v11c0 .41.34.75.75.75h7c.41 0 .75-.34.75-.75V5L9 1.75zM9 1.75V5h3.25",
  text: "M3 4h10M3 8h10M3 12h6",
  git: "M5 2.5v11M5 10.5c0-2.5 6-1.5 6-4.5M11 6a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z",
  home: "M2.5 7 8 2.5 13.5 7v6.25c0 .41-.34.75-.75.75H10v-4H6v4H3.25a.75.75 0 0 1-.75-.75V7z",
  mic: "M8 1.75A2.25 2.25 0 0 0 5.75 4v3.5a2.25 2.25 0 0 0 4.5 0V4A2.25 2.25 0 0 0 8 1.75zM3.75 7.5a4.25 4.25 0 0 0 8.5 0M8 11.75v2.5",
  globe: "M8 14.25A6.25 6.25 0 1 0 8 1.75a6.25 6.25 0 0 0 0 12.5zM1.75 8h12.5M8 1.75C9.6 3.45 10.5 5.65 10.5 8S9.6 12.55 8 14.25C6.4 12.55 5.5 10.35 5.5 8S6.4 3.45 8 1.75z",
  key: "M10 10a4 4 0 1 0-3.86-2.95L2 11.2V14h2.5v-1.5H6V11h1.5l1.05-1.05c.45.03.95.05 1.45.05zM11 5h.01",
  book: "M2.5 3.25c0-.41.34-.75.75-.75H6.5A1.5 1.5 0 0 1 8 4v9.5A1.5 1.5 0 0 0 6.5 12H3.25a.75.75 0 0 1-.75-.75v-8zM13.5 3.25a.75.75 0 0 0-.75-.75H9.5A1.5 1.5 0 0 0 8 4v9.5A1.5 1.5 0 0 1 9.5 12h3.25c.41 0 .75-.34.75-.75v-8z",
  out: "M6 2.5H3.25a.75.75 0 0 0-.75.75v9.5c0 .41.34.75.75.75H6M10.5 11 13.5 8l-3-3M13.5 8H6",
  plus: "M8 3v10M3 8h10",
};

export function Logo({ size = 20 }: { size?: number }) {
  // The docs site's mark (apps/docs/static/img/favicon.svg): voice bars on the brand gradient.
  const g = useId();
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden className="logo">
      <defs><linearGradient id={g} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#0ea5e9" /><stop offset=".55" stopColor="#14b8a6" /><stop offset="1" stopColor="#6366f1" /></linearGradient></defs>
      <circle cx="16" cy="16" r="15" fill={`url(#${g})`} />
      <path d="M9 13v6M13 10v12M17 12v8M21 9v14M25 14v4" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}

export function Icon({ name, label }: { name: keyof typeof PATHS | string; label?: string }) {
  return (
    <svg className="icon" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.75"
         strokeLinecap="round" strokeLinejoin="round" role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <path d={PATHS[name]} />
    </svg>
  );
}

export function Alert({ kind, children }: { kind: "error" | "info" | "success"; children: ReactNode }) {
  return <div className={`alert alert-${kind}`} role={kind === "error" ? "alert" : "status"}>{children}</div>;
}

export function Pill({ status }: { status: string }) {
  return <span className={`pill pill-${status.toLowerCase()}`}><span className="pill-dot" aria-hidden />{status}</span>;
}

export function CopyButton({ text, label = "Copy", onCopied }: { text: string; label?: string; onCopied?: () => void }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="button button-quiet" onClick={async () => {
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        return; // a browser that refuses the clipboard: the text is selectable
      }
      setDone(true);
      onCopied?.();
      setTimeout(() => setDone(false), 2000);
    }}>
      <Icon name={done ? "check" : "copy"} /> {done ? "Copied" : label}
    </button>
  );
}

export function Field({ label, help, children }: { label: string; help?: ReactNode; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {help && <span className="field-help">{help}</span>}
    </label>
  );
}

export const store = { // localStorage for per-browser conveniences only; private windows can refuse it
  get(key: string): string | null {
    try { return localStorage.getItem(key); } catch { return null; }
  },
  set(key: string, value: string): void {
    try { localStorage.setItem(key, value); } catch { /* not kept: fine */ }
  },
};
