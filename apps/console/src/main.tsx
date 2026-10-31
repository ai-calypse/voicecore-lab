// The console shell: first-run setup or sign-in, then a header, the banners and one page per hash route.
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, DEMO, DEMO_REFUSAL, type Status, type Usage } from "./api.ts";
import { parseHash } from "./lib.ts";
import { AgentPage, Agents, go, Keys, Login, Setup, Websites } from "./pages.tsx";
import { Alert } from "./ui.tsx";
import "./styles.css";

function useRoute() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const on = () => setHash(location.hash);
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return parseHash(hash);
}

function App() {
  const route = useRoute();
  const [status, setStatus] = useState<Status | null>(null);
  const [signedIn, setSignedIn] = useState<boolean | null>(DEMO ? true : null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.status().then(async (s) => {
      setStatus(s);
      if (DEMO || s.setup_needed) return;
      setSignedIn(await api.me().then(() => true, () => false));
    }, (e) => setError(e.message));
  }, []);

  if (error) return <main className="narrow"><Alert kind="error">Can't reach the console: {error}</Alert></main>;
  if (!status || signedIn === null && !status.setup_needed) return <main className="narrow"><p className="muted">Loading…</p></main>;
  if (status.setup_needed && !DEMO) {
    return <Setup token={route.query.token} onDone={() => { setStatus({ ...status, setup_needed: false }); setSignedIn(true); go("#/agents"); }} />;
  }
  if (!signedIn) return <Login onDone={() => { setSignedIn(true); if (route.path[0] === "login" || !route.path.length) go("#/agents"); }} />;
  return <Shell status={status} path={route.path} onSignOut={() => setSignedIn(false)} />;
}

function SpendLine() {
  const [u, setU] = useState<Usage | null>(null);
  useEffect(() => { api.usage().then(setU, () => setU(null)); }, []);
  if (!u || u.spent_usd === null || u.cap_usd === null) return null;
  return <span className="spend" title="Provider spend recorded by the voice server's budget ledger">Spent ${u.spent_usd.toFixed(2)} of ${u.cap_usd.toFixed(2)}</span>;
}

function Shell({ status, path, onSignOut }: { status: Status; path: string[]; onSignOut: () => void }) {
  const [section, id, tab] = path;
  const page = section === "agents" && id ? <AgentPage id={id} tab={tab ?? "knowledge"} status={status} />
    : section === "websites" ? <Websites />
    : section === "keys" ? <Keys />
    : <Agents />;
  const current = section === "websites" || section === "keys" ? section : "agents";
  return (
    <>
      {DEMO && <div className="banner banner-demo" role="note">{DEMO_REFUSAL}</div>}
      {status.providers === "free" && !DEMO && (
        <div className="banner banner-info" role="note">Voice is off. Add provider keys: <code>npx create-voicecore keys</code></div>
      )}
      <header className="topbar">
        <a href="#/agents" className="brand" aria-label="VoiceCore console home">
          <span className="brand-mark" aria-hidden />VoiceCore <span className="brand-sub">Console</span>
        </a>
        <nav aria-label="Console">
          {[["agents", "Agents"], ["websites", "Websites"], ["keys", "API keys"]].map(([k, label]) => (
            <a key={k} href={`#/${k}`} aria-current={current === k ? "page" : undefined}>{label}</a>
          ))}
        </nav>
        <div className="topbar-end">
          <SpendLine />
          {!DEMO && <button className="button button-quiet" onClick={() => api.logout().finally(onSignOut)}>Sign out</button>}
        </div>
      </header>
      {page}
    </>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
