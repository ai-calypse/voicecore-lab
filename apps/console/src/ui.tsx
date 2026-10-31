// Small shared pieces: one icon set (16 px, 1.75 stroke), alerts, a copy button, a status pill.
import { useState, type ReactNode } from "react";

const PATHS: Record<string, string> = {
  check: "M3.5 8.5l3 3 6-7",
  copy: "M5.5 5.5V3.25c0-.41.34-.75.75-.75h6.5c.41 0 .75.34.75.75v6.5c0 .41-.34.75-.75.75H10.5M3.25 5.5h6.5c.41 0 .75.34.75.75v6.5c0 .41-.34.75-.75.75h-6.5a.75.75 0 0 1-.75-.75v-6.5c0-.41.34-.75.75-.75z",
  upload: "M8 10.5V2.5M4.5 6 8 2.5 11.5 6M2.5 10.5v2.25c0 .41.34.75.75.75h9.5c.41 0 .75-.34.75-.75V10.5",
  external: "M9.5 2.5h4v4M13.5 2.5 7.5 8.5M11.5 9.5v3.25c0 .41-.34.75-.75.75h-7.5a.75.75 0 0 1-.75-.75v-7.5c0-.41.34-.75.75-.75H6.5",
  dot: "M8 8h.01",
};

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
  return <span className={`pill pill-${status.toLowerCase()}`}>{status}</span>;
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
