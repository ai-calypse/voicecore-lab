// The console shell: first-run setup or sign-in, then a sidebar and one page per hash route.
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, DEMO, DEMO_REFUSAL, type Status } from "./api.ts";
import { parseHash } from "./lib.ts";
import { AgentPage, Agents, go, Home, Keys, Login, Setup, Websites } from "./pages.tsx";
import { Alert, Icon, Logo } from "./ui.tsx";
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
    return <Setup token={route.query.token} onDone={() => { setStatus({ ...status, setup_needed: false }); setSignedIn(true); go("#/"); }} />;
  }
  if (!signedIn) return <Login onDone={() => { setSignedIn(true); if (route.path[0] === "login") go("#/"); }} />;
  return <Shell status={status} path={route.path} onSignOut={() => setSignedIn(false)} />;
}

const NAV = [["home", "Home", "home"], ["agents", "Agents", "mic"], ["websites", "Allowed websites", "globe"], ["keys", "API keys", "key"]] as const;
const DOCS = "https://voicecore-docs.fly.dev/guides/console";

function Shell({ status, path, onSignOut }: { status: Status; path: string[]; onSignOut: () => void }) {
  const [section = "home", id, tab] = path;
  const page = section === "agents" && id ? <AgentPage id={id} tab={tab ?? "knowledge"} status={status} />
    : section === "agents" ? <Agents />
    : section === "websites" ? <Websites />
    : section === "keys" ? <Keys />
    : <Home status={status} />;
  return (
    <div className="app">
      {DEMO && <div className="banner banner-demo" role="note">{DEMO_REFUSAL}</div>}
      <div className="shell">
        <aside className="sidebar">
          <a href="#/" className="brand" aria-label="VoiceCore console home"><Logo size={24} />VoiceCore</a>
          <nav aria-label="Console" className="side-nav">
            {NAV.map(([k, label, icon]) => (
              <a key={k} href={k === "home" ? "#/" : `#/${k}`} aria-current={section === k ? "page" : undefined}><Icon name={icon} />{label}</a>
            ))}
          </nav>
          <div className="side-end">
            {status.providers === "free" && !DEMO && (
              <p className="side-note" role="note"><strong>Voice is off.</strong> Add provider keys with <code>npx create-voicecore keys</code></p>
            )}
            <a href={DOCS} target="_blank" rel="noopener" className="side-link"><Icon name="book" />Docs</a>
            {!DEMO && <button className="side-link" onClick={() => api.logout().finally(onSignOut)}><Icon name="out" />Sign out</button>}
          </div>
        </aside>
        <div className="content">{page}</div>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
