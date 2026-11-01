// The console's pages. Each one loads what it shows, says when it is loading or empty, and shows the server's
// reason when something is refused.
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, DEMO, type Agent, type AgentRow, type Catalog, type Config, type Key, type ProviderKey, type Providers,
  type Status } from "./api.ts";
import { agentStatus, agentSummary, ago, buildLine, greeting, type Build } from "./lib.ts";
import { Alert, CopyButton, Field, Icon, Logo, Pill, store } from "./ui.tsx";

export const go = (hash: string) => { location.hash = hash; };
const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

function useLoad<T>(load: () => Promise<T>, deps: unknown[]): { data: T | null; error: string; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    load().then((d) => live && (setData(d), setError("")), (e) => live && setError(message(e)));
    return () => { live = false; };
  }, [...deps, n]); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error, reload: useCallback(() => setN((x) => x + 1), []) };
}

// --- first run and sign in --------------------------------------------------------------

export function Setup({ token, onDone }: { token?: string; onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.setup(token ?? "", password);
      history.replaceState(null, "", location.pathname); // the setup token leaves the address bar
      onDone();
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  };
  return (
    <main className="narrow auth">
      <Logo size={36} />
      <h1>Set up VoiceCore</h1>
      <p className="lead">Choose the admin password. You'll sign in to this console with it.</p>
      {!token && <Alert kind="info">Open the setup link the installer printed. It ends in <code>#/setup?token=…</code></Alert>}
      <form onSubmit={submit} className="stack">
        <Field label="Admin password" help="At least 12 characters.">
          <input type="password" autoComplete="new-password" minLength={12} required value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {error && <Alert kind="error">{error}</Alert>}
        <button className="button button-primary" disabled={busy || !token}>Create admin</button>
      </form>
    </main>
  );
}

export function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.login(password);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "Wrong password." : message(err));
    }
  };
  return (
    <main className="narrow auth">
      <Logo size={36} />
      <h1>Sign in</h1>
      <form onSubmit={submit} className="stack">
        <Field label="Admin password">
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {error && <Alert kind="error">{error}</Alert>}
        <button className="button button-primary">Sign in</button>
        <div className="stack muted small">
          <p>Forgot it? It's <code>CONSOLE_ADMIN_PASSWORD</code> in the install's <code>.env</code>. In the install folder, this shows it:</p>
          <pre className="command"><code>npx create-voicecore info</code></pre>
        </div>
      </form>
    </main>
  );
}

// --- agents ------------------------------------------------------------------------------

function NewAgent() {
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const a = await api.createAgent(name.trim());
      go(`#/agents/${a.id}/knowledge`);
    } catch (err) {
      setError(message(err));
    }
  };
  return (
    <>
      <button className="button button-primary" disabled={DEMO} onClick={() => dialog.current?.showModal()}><Icon name="plus" />New agent</button>
      <dialog ref={dialog} className="dialog" aria-labelledby="new-agent-title" onClose={() => setError("")}>
        <form onSubmit={create} className="stack">
          <h2 id="new-agent-title">New agent</h2>
          <p className="muted">An agent answers questions from the docs you give it, by voice or text, on your website.</p>
          <Field label="Agent name" help="You can rename it later. Its id comes from this name.">
            <input autoFocus placeholder="Acme Docs" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          {error && <Alert kind="error">{error}</Alert>}
          <div className="dialog-actions">
            <button type="button" className="button" onClick={() => dialog.current?.close()}>Cancel</button>
            <button className="button button-primary">Create agent</button>
          </div>
        </form>
      </dialog>
    </>
  );
}

function AgentsPanel({ title, agents, error }: { title: string; agents: AgentRow[] | null; error: string }) {
  return (
    <section className="panel" aria-labelledby="agents-title">
      <div className="panel-head">
        <h2 id="agents-title">{title}</h2>
        <NewAgent />
      </div>
      {error && <Alert kind="error">{error}</Alert>}
      {!agents && !error && <p className="muted">Loading…</p>}
      {agents?.length === 0 && (
        <div className="empty">
          <h3>No agents yet</h3>
          <p>An agent answers questions from the docs you give it, by voice or text, on your website. Create one to start.</p>
        </div>
      )}
      {!!agents?.length && (
        <ul className="agent-rows">
          {agents.map((a) => (
            <li key={a.id}>
              <a href={`#/agents/${a.id}/knowledge`} className="agent-row">
                <span className="agent-name"><span className="row-title">{a.name}</span><span className="row-id">{a.id}</span></span>
                <span className="muted">{agentSummary(a)}</span>
                <span className="muted small">{a.published ? `Published ${ago(a.published)}` : ""}</span>
                <Pill status={agentStatus(a)} />
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Tile({ label, value, note, href }: { label: string; value: ReactNode; note: ReactNode; href?: string }) {
  const body = <><span className="tile-label">{label}</span><span className="tile-value">{value}</span><span className="tile-note">{note}</span></>;
  return href ? <a href={href} className="tile tile-link">{body}</a> : <div className="tile">{body}</div>;
}

export function Home({ status }: { status: Status }) {
  const agents = useLoad<AgentRow[]>(api.agents, []);
  const site = useLoad(api.site, []);
  const usage = useLoad(api.usage, []);
  const free = status.providers === "free";
  const live = agents.data?.filter((a) => agentStatus(a) === "Live").length ?? 0;
  const origins = site.data?.origins ?? [];
  const u = usage.data;
  const money = (v: number) => `$${v.toFixed(2)}`;
  return (
    <main>
      <header className="page-intro">
        <h1>{greeting(new Date().getHours())}</h1>
        <p className="lead">Here's how your agents are doing.</p>
      </header>
      <section className="tiles" aria-label="This install">
        <Tile label="Agents live" href="#/agents" value={agents.data ? live : "…"}
              note={agents.data ? `of ${agents.data.length} ${agents.data.length === 1 ? "agent" : "agents"}` : ""} />
        <Tile label="Spend" value={free ? money(0) : u?.spent_usd != null ? money(u.spent_usd) : "Not recorded"}
              note={free ? "Free mode spends nothing" : u?.cap_usd != null ? `of ${money(u.cap_usd)} cap${u.today_usd != null ? `, ${money(u.today_usd)} today` : ""}` : "No spend ledger on this install"} />
        <Tile label="Voice" href="#/voice" value={free ? "Off" : "On"} note={free ? "Add your provider keys to turn it on" : "Spoken answers with your provider keys"} />
        <Tile label="Allowed websites" href="#/websites" value={site.data ? origins.length : "…"}
              note={!site.data ? "" : origins.length ? `${origins[0]}${origins.length > 1 ? ` and ${origins.length - 1} more` : ""}` : "None yet: embeds are refused"} />
      </section>
      <AgentsPanel title="Agents" agents={agents.data} error={agents.error} />
    </main>
  );
}

export function Agents() {
  const { data, error } = useLoad<AgentRow[]>(api.agents, []);
  return (
    <main>
      <header className="page-intro">
        <h1>Agents</h1>
        <p className="lead">Each agent answers from its own docs and has its own snippet.</p>
      </header>
      <AgentsPanel title="All agents" agents={data} error={error} />
    </main>
  );
}

const TABS = [["knowledge", "Knowledge"], ["settings", "Settings"], ["test", "Test"], ["embed", "Embed"]] as const;

export function AgentPage({ id, tab, status }: { id: string; tab: string; status: Status }) {
  const { data: agent, error, reload } = useLoad<Agent>(() => api.agent(id), [id]);
  const [build, setBuild] = useState<Agent["build"]>(null);
  const [actionError, setActionError] = useState("");
  const [, rerender] = useState(0);
  useEffect(() => { if (agent) setBuild(agent.build); }, [agent]);

  const active = build?.status === "queued" || build?.status === "running";
  useEffect(() => { // follow a build until it ends, then load the new live version
    if (!active || DEMO) return;
    const t = setInterval(async () => {
      const b = await api.latestBuild(id).catch(() => null);
      if (b && b.status !== "none") {
        setBuild((prev) => (prev ? { ...prev, ...b } : null));
        if (b.status === "done" || b.status === "failed") reload();
      }
    }, 800);
    return () => clearInterval(t);
  }, [active, id, reload]);

  if (error) return <main><Alert kind="error">{error}</Alert></main>;
  if (!agent) return <main><p className="muted">Loading…</p></main>;

  const act = async (f: () => Promise<unknown>) => {
    setActionError("");
    try { await f(); reload(); } catch (e) { setActionError(message(e)); }
  };
  const publish = () => act(async () => { await api.publish(id); setBuild({ id: 0, status: "queued", done: 0, total: 0, version: null, log: "" }); });
  const tested = !!agent.live_version && store.get(`tested:${id}`) === agent.live_version;
  const embedded = store.get(`embedded:${id}`) === "1";
  const steps: [string, string, boolean][] = [
    ["knowledge", "Add docs", agent.sources.length > 0],
    ["knowledge", "Publish", !!agent.live_version],
    ["test", "Test", tested],
    ["embed", "Embed", embedded],
  ];
  const next = steps.findIndex(([, , done]) => !done);
  const state = agentStatus({ enabled: agent.enabled, live_version: agent.live_version, build: build?.status ?? null });

  return (
    <main>
      <nav className="crumbs" aria-label="Breadcrumb"><a href="#/agents">Agents</a> <span aria-hidden>/</span> {agent.config.name}</nav>
      <div className="page-head">
        <div className="title-row">
          <h1>{agent.config.name}</h1>
          <Pill status={state} />
        </div>
        <div className="actions">
          {agent.live_version && (
            <button className="button" disabled={DEMO} onClick={() => act(() => api.setEnabled(id, !agent.enabled))}>
              {agent.enabled ? "Turn off" : "Turn on"}
            </button>
          )}
          <button className="button button-primary" disabled={active || DEMO || !agent.sources.length} onClick={publish}
                  title={!agent.sources.length ? "Add docs first" : undefined}>
            {active ? "Publishing…" : agent.live_version ? "Publish changes" : "Publish"}
          </button>
        </div>
      </div>
      {actionError && <Alert kind="error">{actionError}</Alert>}

      {next !== -1 && ( // the checklist is for getting live; once every step is done it steps aside
        <ol className="steps panel" aria-label="Getting this agent live">
          {steps.map(([to, label, done], i) => (
            <li key={label} className={done ? "done" : i === next ? "next" : ""}>
              <a href={`#/agents/${id}/${to}`} aria-current={i === next ? "step" : undefined}>
                <span className="step-mark" aria-hidden>{done ? <Icon name="check" /> : i + 1}</span>
                <span>{label}</span>
                <span className="sr-only">{done ? "(done)" : i === next ? "(next)" : "(to do)"}</span>
              </a>
            </li>
          ))}
        </ol>
      )}

      <div className="tabs" role="tablist" aria-label="Agent">
        {TABS.map(([key, label]) => (
          <a key={key} role="tab" aria-selected={tab === key} href={`#/agents/${id}/${key}`} className="tab">{label}</a>
        ))}
      </div>
      <section role="tabpanel" className="tab-body">
        {tab === "knowledge" && <Knowledge agent={agent} build={build} reload={reload} />}
        {tab === "settings" && <Settings agent={agent} reload={reload} />}
        {tab === "test" && <TestTab agent={agent} status={status} onSeen={() => { if (agent.live_version) { store.set(`tested:${id}`, agent.live_version); rerender((x) => x + 1); } }} />}
        {tab === "embed" && <Embed agent={agent} onCopied={() => { store.set(`embedded:${id}`, "1"); rerender((x) => x + 1); }} />}
      </section>
    </main>
  );
}

function LiveVersion({ agent, build }: { agent: Agent; build: Agent["build"] }) {
  // What visitors get now (the last published version), then any publish in flight or the reason the last one failed.
  const b = build as Build | null;
  const p = agent.published;
  const busy = b?.status === "queued" || b?.status === "running";
  return (
    <div className="live" aria-live="polite">
      <h2>{p ? "Live version" : "Not published yet"}</h2>
      {p ? (
        <div className="live-facts">
          <p className="live-summary">{buildLine({ status: "done", done: 0, total: 0, version: p.version, log: p.log })}</p>
          <p className="muted small">Published {ago(p.finished)}</p>
          <p className="muted small">Version <span className="mono">{p.version}</span></p>
          {p.log.split("\n").slice(1, -1).map((line) => <p key={line} className="muted small">{line}</p>)}
          {!agent.live_version && <p className="small">Turned off: new sessions are refused until you turn it on.</p>}
        </div>
      ) : !busy && <p className="muted small">Publish builds a version from your sources and settings. Your website can use it once it's live.</p>}
      {busy && b && (
        <div className="build build-running">
          <p>{buildLine(b)}</p>
          {b.status === "running" && b.total > 0 && <progress max={b.total} value={b.done} aria-label="Embedding progress" />}
          {p && <p className="muted small">The live version keeps answering until this one is ready.</p>}
        </div>
      )}
      {b?.status === "failed" && <div className="build build-failed"><p>{buildLine(b)}</p></div>}
    </div>
  );
}

const METHODS = [["upload", "Upload files"], ["text", "Paste text"], ["git", "Git repository"]] as const;
const SOURCE_ICON: Record<string, string> = { text: "text", git: "git" };

function Knowledge({ agent, build, reload }: { agent: Agent; build: Agent["build"]; reload: () => void }) {
  const [result, setResult] = useState<ReactNode>(null);
  const [error, setError] = useState("");
  const [over, setOver] = useState(false);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [repo, setRepo] = useState({ url: "", folder: "docs", ref: "" });
  const [cloning, setCloning] = useState(false);
  const [method, setMethod] = useState<(typeof METHODS)[number][0]>("upload");
  const input = useRef<HTMLInputElement>(null);
  const clone = async (e: FormEvent) => {
    e.preventDefault();
    setError(""); setResult(null); setCloning(true);
    try {
      const r = await api.git(agent.id, repo.url.trim(), repo.folder, repo.ref.trim());
      setResult(<>Added {r.files} {r.files === 1 ? "page" : "pages"} from the repository.{r.skipped.length > 0 && <> Skipped: {r.skipped.join(", ")}.</>}</>);
      setRepo({ url: "", folder: "docs", ref: "" });
      reload();
    } catch (err) { setError(message(err)); }
    setCloning(false);
  };
  const send = async (files: FileList | null) => {
    setError(""); setResult(null);
    for (const f of Array.from(files ?? [])) {
      try {
        const r = await api.upload(agent.id, f);
        setResult(<>Added {r.files} {r.files === 1 ? "page" : "pages"} from {f.name}.{r.skipped.length > 0 && <> Skipped: {r.skipped.join(", ")}.</>}</>);
      } catch (e) {
        setError(`${f.name}: ${message(e)}`);
      }
    }
    reload();
  };
  const paste = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.paste(agent.id, title, text);
      setTitle(""); setText(""); setResult(<>Added “{title}”.</>);
      reload();
    } catch (err) { setError(message(err)); }
  };
  return (
    <div className="split">
      <div className="split-main">
        <section className="panel stack" aria-labelledby="sources-h">
          <h2 id="sources-h">Sources</h2>
          {agent.sources.length === 0 ? <p className="muted">No docs yet. Add files, text or a Git repository below, then publish.</p> : (
          <ul className="rows compact">
            {agent.sources.map((s) => (
              <li key={s.id}>
                <span className="source">
                  <Icon name={SOURCE_ICON[s.kind] ?? "file"} />
                  <span className="row-title">{s.label}</span>
                  <span className="muted small">{s.kind === "text" ? "pasted text" : `${s.files} ${s.files === 1 ? "page" : "pages"}`}</span>
                </span>
                <span className="actions">
                  {s.kind === "git" && (
                    <button className="button button-quiet" disabled={DEMO} onClick={async () => {
                      try { const r = await api.sync(agent.id, s.id); setResult(<>Synced: {r.files} {r.files === 1 ? "page" : "pages"}. Publish to put them live.</>); }
                      catch (e) { setError(message(e)); }
                      reload();
                    }}>Sync</button>
                  )}
                  <button className="button button-quiet" disabled={DEMO} onClick={async () => { await api.removeSource(agent.id, s.id).catch((e) => setError(message(e))); reload(); }}>Remove</button>
                </span>
              </li>
            ))}
          </ul>
          )}
        </section>

        <section className="panel stack" aria-labelledby="add-h">
          <h2 id="add-h">Add docs</h2>
          <fieldset className="segmented">
            <legend className="sr-only">How to add docs</legend>
            {METHODS.map(([k, label]) => (
              <label key={k}><input type="radio" name="method" value={k} checked={method === k} onChange={() => setMethod(k)} />{label}</label>
            ))}
          </fieldset>
          {method === "upload" && (
            <div className={`dropzone${over ? " over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }}
                 onDragLeave={() => setOver(false)} onDrop={(e) => { e.preventDefault(); setOver(false); if (!DEMO) send(e.dataTransfer.files); }}>
              <Icon name="upload" />
              <p><strong>Drop Markdown files or a zip of your docs here</strong></p>
              <p className="muted small">.md, .markdown, .txt or .zip, up to 20 MB. Headings become the sections answers cite.</p>
              <button type="button" className="button" disabled={DEMO} onClick={() => input.current?.click()}>Choose files</button>
              <input ref={input} type="file" multiple accept=".md,.markdown,.txt,.zip" hidden aria-label="Docs files"
                     onChange={(e) => { send(e.target.files); e.target.value = ""; }} />
            </div>
          )}
          {method === "text" && (
            <form onSubmit={paste} className="stack">
              <Field label="Title"><input required maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} disabled={DEMO} /></Field>
              <Field label="Text" help="For an FAQ or a short note. The title becomes its heading.">
                <textarea required rows={6} value={text} onChange={(e) => setText(e.target.value)} disabled={DEMO} />
              </Field>
              <button className="button" disabled={DEMO}>Add text</button>
            </form>
          )}
          {method === "git" && (
            <form onSubmit={clone} className="stack">
              <Field label="Repository URL" help="A public repository over https.">
                <input type="url" required placeholder="https://github.com/acme/docs" value={repo.url} onChange={(e) => setRepo({ ...repo, url: e.target.value })} disabled={DEMO} />
              </Field>
              <div className="grid-2 tight">
                <Field label="Folder" help="Where the Markdown lives. Empty: the whole repository.">
                  <input value={repo.folder} onChange={(e) => setRepo({ ...repo, folder: e.target.value })} disabled={DEMO} />
                </Field>
                <Field label="Branch or tag" help="Empty: the default branch.">
                  <input value={repo.ref} onChange={(e) => setRepo({ ...repo, ref: e.target.value })} disabled={DEMO} />
                </Field>
              </div>
              <button className="button" disabled={DEMO || cloning}>{cloning ? "Cloning…" : "Add repository"}</button>
            </form>
          )}
          {result && <Alert kind="success">{result}</Alert>}
          {error && <Alert kind="error">{error}</Alert>}
        </section>
      </div>
      <aside className="panel split-side"><LiveVersion agent={agent} build={build} /></aside>
    </div>
  );
}

function Settings({ agent, reload }: { agent: Agent; reload: () => void }) {
  const { data: catalog } = useLoad<Catalog>(api.catalog, []);
  const [form, setForm] = useState<Config>({ ...agent.config, turn_taking: agent.config.turn_taking ?? "quick" });
  const [terms, setTerms] = useState(agent.config.keyterms.join(", "));
  const [state, setState] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const set = (k: keyof Config) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const save = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const keyterms = terms.split(",").map((t) => t.trim()).filter(Boolean);
      await api.saveSettings(agent.id, { ...form, first_message: form.first_message || null, keyterms });
      setState({ kind: "success", text: "Saved. Publish to put these settings live." });
      reload();
    } catch (err) { setState({ kind: "error", text: message(err) }); }
  };
  return (
    <form onSubmit={save} className="stack-lg form-wide">
      <fieldset className="panel group">
        <legend>Answers</legend>
        <Field label="Name" help="Shown to visitors as the assistant's name.">
          <input required maxLength={80} value={form.name} onChange={set("name")} disabled={DEMO} />
        </Field>
        <Field label="Docs URL" help="Where these docs are published. Answers link to the section they cite. Leave it empty to cite titles only.">
          <input type="url" placeholder="https://docs.example.com/" value={form.docs_url} onChange={set("docs_url")} disabled={DEMO} />
        </Field>
        <Field label="First message" help="Optional. Said when someone opens the assistant.">
          <input maxLength={300} value={form.first_message ?? ""} onChange={set("first_message")} disabled={DEMO} />
        </Field>
        <Field label="Instructions" help="Optional. Added after VoiceCore's own rules (answer only from your docs, cite every fact), never instead of them.">
          <textarea rows={4} maxLength={2000} value={form.instructions} onChange={set("instructions")} disabled={DEMO} />
        </Field>
      </fieldset>
      <fieldset className="panel group">
        <legend>Voice and model</legend>
        <div className="grid-2 tight">
          <Field label="Voice">
            <select value={form.voice} onChange={set("voice")} disabled={DEMO}>
              {Object.entries(catalog?.voices ?? { [form.voice]: form.voice }).map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
          </Field>
          <Field label="Model">
            <select value={form.llm} onChange={set("llm")} disabled={DEMO}>
              {(catalog?.llms ?? [form.llm]).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </Field>
        </div>
        <Field label="Key terms" help="Optional, comma separated: names the speech recognizer should expect. Skip everyday words: they get heard where they weren't said.">
          <input value={terms} onChange={(e) => setTerms(e.target.value)} disabled={DEMO} />
        </Field>
        <Field label="Turn-taking" help="When the assistant decides you've finished speaking.">
          <select value={form.turn_taking} onChange={set("turn_taking")} disabled={DEMO}>
            <option value="quick">Quick: replies after a short pause (best for short questions)</option>
            <option value="patient">Patient: waits for 0.8 s of silence (people who pause mid-sentence)</option>
          </select>
        </Field>
      </fieldset>
      {state && <Alert kind={state.kind}>{state.text}</Alert>}
      <div><button className="button button-primary" disabled={DEMO}>Save settings</button></div>
    </form>
  );
}

function DemoAssistant() {
  // The docs site forbids framing, so the demo loads the real widget into this page instead, talking to the live
  // VoiceCore docs assistant (the same docs this demo agent was published from).
  useEffect(() => {
    if (document.querySelector("script[data-voicecore]")) return;
    const s = document.createElement("script");
    s.src = "/embed/voicecore.js";
    s.dataset.voicecore = "";
    s.dataset.endpoint = import.meta.env.VITE_DEMO_GATEWAY ?? "https://voicecore.fly.dev";
    if (import.meta.env.VITE_DEMO_SITEKEY) s.dataset.turnstileSitekey = import.meta.env.VITE_DEMO_SITEKEY;
    s.dataset.title = "Ask the docs";
    s.dataset.name = "VoiceCore docs assistant";
    document.body.append(s);
  }, []);
  return (
    <div className="panel stack">
      <p>In this read-only demo, the Test tab is the live VoiceCore docs assistant, answering from the same docs this agent was published from. Open it with <strong>Ask the docs</strong> in the corner and ask by voice or text.</p>
      <p className="muted small">On your own install, this tab frames a test page holding exactly your agent's snippet.</p>
    </div>
  );
}

function TestTab({ agent, status, onSeen }: { agent: Agent; status: Status; onSeen: () => void }) {
  useEffect(() => { onSeen(); }, [agent.live_version]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!agent.live_version) return <div className="panel"><div className="empty"><h2>Publish first</h2><p>Once the agent is live, you can talk to it here.</p></div></div>;
  if (DEMO) return <DemoAssistant />;
  const src = `/preview/${agent.id}`;
  return (
    <div className="panel stack">
      <p>This frame holds the exact snippet from the Embed tab. Open the assistant in its corner and ask a question from your docs.</p>
      {status.providers === "free" && <p className="muted small">Free mode: answers are the closest section of your docs, in text. Add provider keys for voice and written answers.</p>}
      <iframe className="preview" src={src} title={`Test ${agent.config.name}`} allow="microphone; clipboard-write" />
      <p><a href={src} target="_blank" rel="noopener">Open the test page in a new tab <Icon name="external" /></a></p>
    </div>
  );
}

function Embed({ agent, onCopied }: { agent: Agent; onCopied: () => void }) {
  return (
    <div className="panel stack form-wide">
      <h2>Add it to your website</h2>
      <p>Paste this line before <code>&lt;/body&gt;</code> on every page where the assistant should appear.</p>
      {DEMO && <Alert kind="info">Illustrative: this demo publishes nothing, so this snippet does not start a session. Install VoiceCore to get a working one.</Alert>}
      <div className="snippet">
        <pre><code>{agent.snippet}</code></pre>
        <CopyButton text={agent.snippet} label="Copy snippet" onCopied={onCopied} />
      </div>
      {!agent.live_version && <Alert kind="info">Publish the agent first: until then the snippet shows the assistant but it can't start a session.</Alert>}
      <ul className="notes">
        <li>Add your website under <a href="#/websites">Allowed websites</a>, or the snippet won't start a conversation there.</li>
        <li>React or Next.js: put the same tag in your root layout (with Next.js, the <code>Script</code> component and <code>strategy="afterInteractive"</code>).</li>
        <li>Docusaurus: add it to <code>scripts</code> in <code>docusaurus.config.js</code> with <code>data-agent</code> set.</li>
        <li>A Content-Security-Policy on your site must allow the voice server in <code>script-src</code> and <code>connect-src</code> (both <code>https:</code> and <code>wss:</code>).</li>
      </ul>
    </div>
  );
}

// --- install-wide --------------------------------------------------------------------------

export function Websites() {
  const { data, error, reload } = useLoad(api.site, []);
  const [text, setText] = useState<string | null>(null);
  const [state, setState] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const value = text ?? data?.origins.join("\n") ?? "";
  const save = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.saveSite(value.split("\n").map((l) => l.trim()).filter(Boolean));
      setState({ kind: "success", text: "Saved. The new list applies within a second, with no restart." });
      setText(null); reload();
    } catch (err) { setState({ kind: "error", text: message(err) }); }
  };
  return (
    <main className="narrow-wide">
      <header className="page-intro">
        <h1>Allowed websites</h1>
        <p className="lead">The websites where your agents may answer. When someone opens the assistant, VoiceCore checks the address of the page it's on and refuses any site not on this list, so nobody can copy your snippet onto their own site and run up your provider bill.</p>
      </header>
      {error && <Alert kind="error">{error}</Alert>}
      {data && !data.origins.length && (
        <Alert kind="info">No websites yet. The Test tab here always works, but the snippet won't start a conversation on your own site until you add it below.</Alert>
      )}
      <form onSubmit={save} className="panel stack">
        <Field label="Website addresses" help={<>One per line, without a path. Applies to every agent on this install.</>}>
          <textarea rows={5} value={value} onChange={(e) => setText(e.target.value)} disabled={DEMO} spellCheck={false} />
        </Field>
        <ul className="notes small">
          <li><code>docs.acme.com</code> allows that site.</li>
          <li><code>https://www.acme.com</code> allows its secure pages only.</li>
          <li><code>*.acme.com</code> allows every subdomain of acme.com.</li>
        </ul>
        {state && <Alert kind={state.kind}>{state.text}</Alert>}
        <div><button className="button button-primary" disabled={DEMO}>Save websites</button></div>
      </form>
    </main>
  );
}

const PROVIDERS = [
  { id: "deepgram", name: "Deepgram", what: "Hears the visitor and speaks the answers.", link: "https://console.deepgram.com/" },
  { id: "openrouter", name: "OpenRouter", what: "Runs the language model that writes the answers.", link: "https://openrouter.ai/settings/keys" },
] as const;

export function Voice({ onChange }: { onChange: () => void }) {
  const { data, error, reload } = useLoad<Providers>(api.providers, []);
  const changed = () => { reload(); onChange(); };
  return (
    <main className="narrow-wide">
      <header className="page-intro">
        <h1>Voice</h1>
        <p className="lead">Voice runs on two providers, billed to your own accounts. Add a key for each and the next conversation speaks and listens, with no restart. Each key is checked with its provider when you save it, and never shown again.</p>
      </header>
      {error && <Alert kind="error">{error}</Alert>}
      {data && (
        <Alert kind={data.voice ? "success" : "info"}>
          {data.voice ? "Voice is on: new conversations speak and listen." : "Voice is off: the assistant answers typed questions with the closest section of your docs."}
        </Alert>
      )}
      {data && PROVIDERS.map((p) => <ProviderKeyForm key={p.id} {...p} state={data[p.id]} editable={data.editable} onChange={changed} />)}
    </main>
  );
}

function ProviderKeyForm({ id, name, what, link, state, editable, onChange }: { id: string; name: string; what: string; link: string;
  state: ProviderKey; editable: boolean; onChange: () => void }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const run = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      await action();
      setKey(""); setResult({ kind: "success", text: done }); onChange();
    } catch (err) { setResult({ kind: "error", text: message(err) }); } finally { setBusy(false); }
  };
  const save = (e: FormEvent) => { e.preventDefault(); run(() => api.setProviderKey(id, key), `Saved. ${name} accepted the key.`); };
  const where = state.source === "dashboard" ? <>Saved here, ending in <code>…{state.last4}</code>.</>
    : state.source === "server" ? <>Set on the server, ending in <code>…{state.last4}</code>.{editable && " A key saved here takes its place."}</>
    : "No key yet.";
  return (
    <form onSubmit={save} className="panel stack" aria-labelledby={`${id}-title`}>
      <div className="panel-head">
        <h2 id={`${id}-title`}>{name}</h2>
        <Pill status={state.source ? "Set" : "Missing"} />
      </div>
      <p className="muted">{what} <a href={link} target="_blank" rel="noopener">Create a key at {name}</a></p>
      <p>{where}</p>
      {editable ? (
        <>
          <Field label={`${state.source ? "New" : ""} ${name} API key`.trim()}>
            <input type="password" autoComplete="off" spellCheck={false} required value={key} onChange={(e) => setKey(e.target.value)} disabled={DEMO || busy} />
          </Field>
          {result && <Alert kind={result.kind}>{result.text}</Alert>}
          <div className="actions">
            <button className="button button-primary" disabled={DEMO || busy}>{busy ? `Checking with ${name}…` : "Save key"}</button>
            {state.source === "dashboard" && (
              <button type="button" className="button" disabled={DEMO || busy} onClick={() => run(() => api.removeProviderKey(id), "Removed.")}>Remove</button>
            )}
          </div>
        </>
      ) : <p className="muted small">This install's keys are set on its server, in its environment.</p>}
    </form>
  );
}

export function Keys() {
  const { data, error, reload } = useLoad<Key[]>(api.keys, []);
  const [label, setLabel] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const k = await api.createKey(label.trim());
      setCreated(k.key); setLabel(""); reload();
    } catch (err) { setActionError(message(err)); }
  };
  return (
    <main className="narrow-wide">
      <header className="page-intro">
        <h1>API keys</h1>
        <p className="lead">For scripts and CI: send <code>Authorization: Bearer vck_…</code> to the same API this console uses. The reference is at <a href="/api/docs">/api/docs</a>.</p>
      </header>
      <section className="panel stack" aria-label="Keys">
        <form onSubmit={create} className="inline-form">
          <input aria-label="Key name" placeholder="What it's for, e.g. docs CI" required maxLength={80} value={label} onChange={(e) => setLabel(e.target.value)} disabled={DEMO} />
          <button className="button button-primary" disabled={DEMO}>Create key</button>
        </form>
        {created && (
          <Alert kind="success">
            <p><strong>Copy this key now.</strong> It is not shown again.</p>
            <div className="snippet"><pre><code>{created}</code></pre><CopyButton text={created} /></div>
          </Alert>
        )}
        {(error || actionError) && <Alert kind="error">{error || actionError}</Alert>}
        {data?.length === 0 && <p className="muted">No keys yet.</p>}
        {!!data?.length && (
          <ul className="rows compact">
            {data.map((k) => (
              <li key={k.id}>
                <span><span className="row-title">{k.label}</span> <span className="muted small">created {new Date(k.created * 1000).toLocaleDateString()}</span></span>
                <button className="button button-quiet" disabled={DEMO} onClick={async () => { await api.revokeKey(k.id).catch((e) => setActionError(message(e))); reload(); }}>Revoke</button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
