// The console's pages. Each one loads what it shows, says when it is loading or empty, and shows the server's
// reason when something is refused.
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, DEMO, type Agent, type AgentRow, type Catalog, type Config, type Key, type Status } from "./api.ts";
import { agentStatus, buildLine, type Build } from "./lib.ts";
import { Alert, CopyButton, Field, Icon, Pill, store } from "./ui.tsx";

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
    <main className="narrow">
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
    <main className="narrow">
      <h1>Sign in</h1>
      <form onSubmit={submit} className="stack">
        <Field label="Admin password">
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {error && <Alert kind="error">{error}</Alert>}
        <button className="button button-primary">Sign in</button>
        <p className="muted small">Lost the password? Run <code>docker compose exec console python -m voicecore_console reset-admin</code> for a new setup link.</p>
      </form>
    </main>
  );
}

// --- agents ------------------------------------------------------------------------------

export function Agents() {
  const { data, error } = useLoad<AgentRow[]>(api.agents, []);
  const [name, setName] = useState("");
  const [createError, setCreateError] = useState("");
  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const a = await api.createAgent(name.trim());
      go(`#/agents/${a.id}/knowledge`);
    } catch (err) {
      setCreateError(message(err));
    }
  };
  return (
    <main>
      <div className="page-head">
        <h1>Agents</h1>
        <form onSubmit={create} className="inline-form" aria-label="New agent">
          <input aria-label="New agent name" placeholder="Agent name, e.g. Acme Docs" required maxLength={80}
                 value={name} onChange={(e) => setName(e.target.value)} disabled={DEMO} />
          <button className="button button-primary" disabled={DEMO}>Create agent</button>
        </form>
      </div>
      {createError && <Alert kind="error">{createError}</Alert>}
      {error && <Alert kind="error">{error}</Alert>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data?.length === 0 && (
        <div className="empty">
          <h2>No agents yet</h2>
          <p>An agent answers questions from the docs you give it, by voice or text, on your website. Name one above to start.</p>
        </div>
      )}
      {!!data?.length && (
        <ul className="rows">
          {data.map((a) => (
            <li key={a.id}>
              <a href={`#/agents/${a.id}/knowledge`} className="row-link">
                <span className="row-title">{a.name}</span>
                <code className="muted small">{a.id}</code>
              </a>
              <Pill status={agentStatus(a)} />
            </li>
          ))}
        </ul>
      )}
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

      <ol className="steps" aria-label="Getting this agent live">
        {steps.map(([to, label, done], i) => (
          <li key={label} className={done ? "done" : ""}>
            <a href={`#/agents/${id}/${to}`}>
              <span className="step-mark" aria-hidden>{done ? <Icon name="check" /> : i + 1}</span>
              <span>{label}</span>
              <span className="sr-only">{done ? "(done)" : "(to do)"}</span>
            </a>
          </li>
        ))}
      </ol>

      <div className="tabs" role="tablist" aria-label="Agent">
        {TABS.map(([key, label]) => (
          <a key={key} role="tab" aria-selected={tab === key} href={`#/agents/${id}/${key}`} className="tab">{label}</a>
        ))}
      </div>
      <section role="tabpanel" className="panel">
        {tab === "knowledge" && <Knowledge agent={agent} build={build} reload={reload} />}
        {tab === "settings" && <Settings agent={agent} reload={reload} />}
        {tab === "test" && <TestTab agent={agent} status={status} onSeen={() => { if (agent.live_version) { store.set(`tested:${id}`, agent.live_version); rerender((x) => x + 1); } }} />}
        {tab === "embed" && <Embed agent={agent} onCopied={() => { store.set(`embedded:${id}`, "1"); rerender((x) => x + 1); }} />}
      </section>
    </main>
  );
}

function BuildStatus({ build }: { build: Agent["build"] }) {
  const b = build as Build | null;
  return (
    <div className={`build build-${b?.status ?? "none"}`} aria-live="polite">
      <p>{buildLine(b)}</p>
      {b?.status === "running" && b.total > 0 && <progress max={b.total} value={b.done} aria-label="Embedding progress" />}
      {b?.status === "done" && b.log.split("\n").slice(1, -1).map((line) => <p key={line} className="muted small">{line}</p>)}
    </div>
  );
}

function Knowledge({ agent, build, reload }: { agent: Agent; build: Agent["build"]; reload: () => void }) {
  const [result, setResult] = useState<ReactNode>(null);
  const [error, setError] = useState("");
  const [over, setOver] = useState(false);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const input = useRef<HTMLInputElement>(null);
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
    <div className="grid-2">
      <div className="stack">
        <h2>Add docs</h2>
        <div className={`dropzone${over ? " over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }}
             onDragLeave={() => setOver(false)} onDrop={(e) => { e.preventDefault(); setOver(false); if (!DEMO) send(e.dataTransfer.files); }}>
          <Icon name="upload" />
          <p><strong>Drop Markdown files or a zip of your docs here</strong></p>
          <p className="muted small">.md, .markdown, .txt or .zip, up to 20 MB. Headings become the sections answers cite.</p>
          <button type="button" className="button" disabled={DEMO} onClick={() => input.current?.click()}>Choose files</button>
          <input ref={input} type="file" multiple accept=".md,.markdown,.txt,.zip" hidden aria-label="Docs files"
                 onChange={(e) => { send(e.target.files); e.target.value = ""; }} />
        </div>
        <form onSubmit={paste} className="stack">
          <h3>Or paste text</h3>
          <Field label="Title"><input required maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} disabled={DEMO} /></Field>
          <Field label="Text" help="For an FAQ or a short note. The title becomes its heading.">
            <textarea required rows={5} value={text} onChange={(e) => setText(e.target.value)} disabled={DEMO} />
          </Field>
          <button className="button" disabled={DEMO}>Add text</button>
        </form>
        {result && <Alert kind="success">{result}</Alert>}
        {error && <Alert kind="error">{error}</Alert>}
      </div>
      <div className="stack">
        <h2>Sources</h2>
        {agent.sources.length === 0 ? <p className="muted">No docs yet. Add a file or some text, then publish.</p> : (
          <ul className="rows compact">
            {agent.sources.map((s) => (
              <li key={s.id}>
                <span><span className="row-title">{s.label}</span> <span className="muted small">{s.kind === "text" ? "pasted text" : `${s.files} ${s.files === 1 ? "page" : "pages"}`}</span></span>
                <button className="button button-quiet" disabled={DEMO} onClick={async () => { await api.removeSource(agent.id, s.id).catch((e) => setError(message(e))); reload(); }}>Remove</button>
              </li>
            ))}
          </ul>
        )}
        <h2>Publishing</h2>
        <BuildStatus build={build} />
        <p className="muted small">Publishing builds a new version from these sources and your settings. The live version keeps answering until the new one is ready.</p>
      </div>
    </div>
  );
}

function Settings({ agent, reload }: { agent: Agent; reload: () => void }) {
  const { data: catalog } = useLoad<Catalog>(api.catalog, []);
  const [form, setForm] = useState<Config>(agent.config);
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
    <form onSubmit={save} className="stack form-wide">
      <Field label="Name"><input required maxLength={80} value={form.name} onChange={set("name")} disabled={DEMO} /></Field>
      <Field label="Docs URL" help="Where these docs are published. Answers link to the section they cite. Leave it empty to cite titles only.">
        <input type="url" placeholder="https://docs.example.com/" value={form.docs_url} onChange={set("docs_url")} disabled={DEMO} />
      </Field>
      <Field label="First message" help="Optional. Said when someone opens the assistant.">
        <input maxLength={300} value={form.first_message ?? ""} onChange={set("first_message")} disabled={DEMO} />
      </Field>
      <Field label="Instructions" help="Optional. Added after VoiceCore's own rules (answer only from your docs, cite every fact), never instead of them.">
        <textarea rows={4} maxLength={2000} value={form.instructions} onChange={set("instructions")} disabled={DEMO} />
      </Field>
      <div className="grid-2">
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
      <Field label="Key terms" help="Optional, comma separated: product names the speech recognizer should expect.">
        <input value={terms} onChange={(e) => setTerms(e.target.value)} disabled={DEMO} />
      </Field>
      {state && <Alert kind={state.kind}>{state.text}</Alert>}
      <div><button className="button button-primary" disabled={DEMO}>Save settings</button></div>
    </form>
  );
}

function TestTab({ agent, status, onSeen }: { agent: Agent; status: Status; onSeen: () => void }) {
  useEffect(() => { onSeen(); }, [agent.live_version]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!agent.live_version) return <div className="empty"><h2>Publish first</h2><p>Once the agent is live, you can talk to it here.</p></div>;
  const src = DEMO ? `${import.meta.env.BASE_URL}preview.html` : `/preview/${agent.id}`;
  return (
    <div className="stack">
      <p>This frame holds the exact snippet from the Embed tab. Open the assistant in its corner and ask a question from your docs.</p>
      {status.providers === "free" && <p className="muted small">Free mode: answers are the closest section of your docs, in text. Add provider keys for voice and written answers.</p>}
      <iframe className="preview" src={src} title={`Test ${agent.config.name}`} allow="microphone; clipboard-write" />
      <p><a href={src} target="_blank" rel="noopener">Open the test page in a new tab <Icon name="external" /></a></p>
    </div>
  );
}

function Embed({ agent, onCopied }: { agent: Agent; onCopied: () => void }) {
  return (
    <div className="stack form-wide">
      <h2>Add it to your website</h2>
      <p>Paste this line before <code>&lt;/body&gt;</code> on every page where the assistant should appear.</p>
      <div className="snippet">
        <pre><code>{agent.snippet}</code></pre>
        <CopyButton text={agent.snippet} label="Copy snippet" onCopied={onCopied} />
      </div>
      {!agent.live_version && <Alert kind="info">Publish the agent first: until then the snippet shows the assistant but it can't start a session.</Alert>}
      <ul className="notes">
        <li>Add your website under <a href="#/websites">Websites</a>, or browsers on it will be refused.</li>
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
      setState({ kind: "success", text: "Saved. The voice server picks this up within a second." });
      setText(null); reload();
    } catch (err) { setState({ kind: "error", text: message(err) }); }
  };
  return (
    <main className="narrow-wide">
      <h1>Websites</h1>
      <p className="lead">Browsers may start a session only from these sites. Use the host, such as <code>docs.example.com</code>, one per line; add <code>https://</code> to allow only secure pages.</p>
      {error && <Alert kind="error">{error}</Alert>}
      <form onSubmit={save} className="stack">
        <Field label="Websites allowed to embed"><textarea rows={6} value={value} onChange={(e) => setText(e.target.value)} disabled={DEMO} spellCheck={false} /></Field>
        {state && <Alert kind={state.kind}>{state.text}</Alert>}
        <div><button className="button button-primary" disabled={DEMO}>Save websites</button></div>
      </form>
    </main>
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
      <h1>API keys</h1>
      <p className="lead">For scripts and CI: send <code>Authorization: Bearer vck_…</code> to the same API this console uses. The reference is at <a href="/api/docs">/api/docs</a>.</p>
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
    </main>
  );
}
