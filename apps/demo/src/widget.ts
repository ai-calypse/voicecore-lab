// Embeddable voice + text widget (S08-T01). One classic script:
//   <script src="https://…/voicecore.js" data-endpoint="https://gateway.example" data-title="Ask the docs"></script>
// Renders in a Shadow DOM so the host page's CSS cannot reach it, and talks to the gateway only
// (a short-lived session token from POST /v1/session; provider keys never reach the browser).
// When an answer cites a docs section it dispatches "voicecore:navigate" on window ({url, title}); a host that
// opens the section itself calls preventDefault() (the docs site does, without a reload, so the session lives on).
import { startPlayout, VoiceClient, type PlayoutHandle } from "@voicecore/web-sdk";
import css from "./widget.css?inline";

type Ev = { type: string; [k: string]: unknown };
type Source = { n: number; title: string; url: string };

const script = document.currentScript as HTMLScriptElement | null;
const endpoint = (script?.dataset.endpoint ?? location.origin).replace(/\/$/, "");
const label = script?.dataset.title ?? "Ask the docs";
const name = script?.dataset.name ?? "Docs assistant";
const sitekey = script?.dataset.turnstileSitekey; // data-turnstile-sitekey: ask Cloudflare Turnstile before each new session

type Turnstile = { render(el: HTMLElement, o: Record<string, unknown>): string; remove(id: string): void };
class HumanCheckFailed extends Error {}
let turnstileApi: Promise<Turnstile> | null = null;
const loadTurnstile = () => (turnstileApi ??= new Promise<Turnstile>((resolve, reject) => {
  const s = document.createElement("script");
  s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
  s.async = true;
  s.onload = () => { const t = (window as unknown as { turnstile?: Turnstile }).turnstile; if (t) resolve(t); else reject(new HumanCheckFailed()); };
  s.onerror = () => { turnstileApi = null; reject(new HumanCheckFailed()); };
  document.head.append(s);
}));

/** A Turnstile token. The check renders in the page (not the widget's shadow root) and shows only if it needs the user. */
async function humanCheck(): Promise<string> {
  const ts = await loadTurnstile();
  const box = document.createElement("div");
  box.style.cssText = "position:fixed;right:24px;bottom:96px;z-index:2147483647";
  document.body.append(box);
  let id = "";
  try {
    return await new Promise<string>((resolve, reject) => {
      id = ts.render(box, { sitekey, appearance: "interaction-only", callback: resolve,
        "error-callback": () => reject(new HumanCheckFailed()), "expired-callback": () => reject(new HumanCheckFailed()) });
    });
  } finally {
    if (id) ts.remove(id);
    box.remove();
  }
}

const ICON = {
  mic: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z"/></svg>',
  stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>',
  send: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.4 20.4 21 12 3.4 3.6 3.39 10.1 15 12 3.39 13.9z"/></svg>',
  close: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12 19 6.4 17.6 5 12 10.6z"/></svg>',
};

function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string> = {}, ...kids: (Node | string)[]) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  e.append(...kids);
  return e;
}

function mount() {
  const host = h("div", { "data-voicecore": "" });
  const root = host.attachShadow({ mode: "open" });
  root.append(h("style", {}, css));
  document.body.append(host);

  const launcher = h("button", { class: "launcher", type: "button", "aria-expanded": "false", "aria-controls": "vc-panel" },
    h("span", { class: "orb small", "aria-hidden": "true" }), label);
  const status = h("p", { class: "status", role: "status", "aria-live": "polite" }, "Tap the mic and ask me anything about these docs.");
  const mic = h("button", { class: "mic", type: "button", "aria-label": "Start talking", "aria-pressed": "false" });
  mic.innerHTML = ICON.mic;
  const stage = h("div", { class: "stage" }, h("span", { class: "orb big", "aria-hidden": "true" }), mic);
  const log = h("ol", { class: "log", "aria-label": "Conversation" });
  const input = h("input", { type: "text", name: "q", placeholder: "Or type a question…", "aria-label": "Your question", autocomplete: "off", maxlength: "500" });
  const send = h("button", { type: "submit", class: "send", "aria-label": "Send" });
  send.innerHTML = ICON.send;
  const form = h("form", { class: "ask" }, input, send);
  const close = h("button", { type: "button", class: "close", "aria-label": "Close and end the session" });
  close.innerHTML = ICON.close;
  const panel = h("section", { class: "panel", id: "vc-panel", role: "dialog", "aria-label": name, hidden: "" },
    h("header", {}, h("p", { class: "title" }, name), close), stage, status, log, form,
    h("p", { class: "foot" }, "Answers come from these docs and cite them. Audio is not stored."));
  root.append(launcher, panel);

  let client: VoiceClient | null = null;
  let playout: PlayoutHandle | null = null;
  let micOn = false;
  let micBusy = false; // a start or stop is in flight (getUserMedia can take seconds)
  let connecting: Promise<void> | null = null;
  let epoch = 0; // bumped by end(): an older connect() that finishes later cleans up after itself
  const sources = new Map<number, Source[]>();
  let partial: HTMLLIElement | null = null;

  const setState = (s: string, text: string) => {
    panel.dataset.state = s;
    status.textContent = text;
  };
  const say = (who: "user" | "agent" | "note", text: string) => {
    const li = h("li", { class: who }, text);
    log.append(li);
    log.scrollTop = log.scrollHeight;
    return li;
  };
  const open = (s: Source) => // true when the host page opened the section itself
    !dispatchEvent(new CustomEvent("voicecore:navigate", { detail: { url: s.url, title: s.title }, cancelable: true }));
  const link = (s: Source, attrs: Record<string, string>, text: string) => {
    const a = h("a", { href: s.url, target: "_blank", rel: "noopener", ...attrs }, text);
    a.addEventListener("click", (ev) => { if (open(s)) ev.preventDefault(); });
    return a;
  };
  const answer = (gen: number, text: string) => {
    const li = h("li", { class: "agent", "data-gen": String(gen) });
    const src = sources.get(gen) ?? [];
    for (const part of text.split(/(\[\d+\])/)) { // [n] becomes a link to the cited docs section
      const m = part.match(/^\[(\d+)\]$/);
      const s = m && src.find((x) => x.n === Number(m[1]));
      li.append(s ? link(s, { class: "cite", title: s.title }, `[${s.n}]`) : part);
    }
    if (src.length) li.append(h("ul", { class: "sources", "aria-label": "Sources" }, ...src.map((s) => h("li", {}, link(s, {}, `[${s.n}] ${s.title}`)))));
    log.append(li);
    log.scrollTop = log.scrollHeight;
  };

  const onEvent = (e: Ev) => {
    switch (e.type) {
      case "user.speech_started": setState("listening", "Listening…"); break;
      case "transcript.partial":
        if (!e.text) break;
        partial ??= say("user", "");
        partial.textContent = String(e.text);
        partial.classList.add("live");
        break;
      case "transcript.final":
        if (partial) { partial.textContent = String(e.text); partial.classList.remove("live"); partial = null; } else say("user", String(e.text));
        break;
      case "agent.generation_started": partial = null; setState("thinking", "Thinking…"); break;
      case "answer.sources": { // arrives while the answer is spoken: open the first cited section now
        const src = e.sources as Source[];
        sources.set(Number(e.gen), src);
        if (src[0]) open(src[0]);
        break;
      }
      case "agent.text": answer(Number(e.gen), String(e.text)); break;
      case "playout.started": setState("speaking", "Speaking… start talking to interrupt."); break;
      case "playout.stopped": // after a barge-in the user is still talking: keep "Listening…"
        if (e.reason === "done") setState("ready", micOn ? "Listening. Ask another question." : "Ask another question.");
        break;
      case "agent.cancel": setState("listening", "Listening…"); break;
      case "session.ended": setState("ended", "The session ended. Close and reopen to start again."); break;
      case "socket.reconnecting": if (client) setState("connecting", "Reconnecting…"); break;
      case "welcome": if (client) setState("ready", micOn ? "Listening. Ask another question." : "Ready. Tap the mic or type a question."); break;
      case "socket.closed": if (client) setState("ended", "Disconnected. Close and reopen to start again."); break;
    }
  };

  const newToken = async (): Promise<string> => { // a short-lived token from the gateway; the reconnect asks again if needed
    // a form body keeps the request a CORS "simple request": no preflight
    const body = sitekey ? new URLSearchParams({ "cf-turnstile-response": await humanCheck() }) : undefined;
    const res = await fetch(`${endpoint}/v1/session`, { method: "POST", body });
    if (res.status === 403 && sitekey) throw new HumanCheckFailed();
    if (!res.ok) throw new Error(`token request failed (${res.status})`);
    return (await res.json()).token;
  };

  const connect = () => (connecting ??= (async () => {
    const mine = epoch;
    let c: VoiceClient | null = null, p: PlayoutHandle | null = null;
    const stale = () => mine !== epoch;
    try {
      setState("connecting", "Connecting…");
      const token = await newToken();
      if (stale()) throw new Error("closed");
      p = await startPlayout((e) => { onEvent(e); c?.send(e); });
      if (stale()) throw new Error("closed");
      c = new VoiceClient({ url: endpoint.replace(/^http/, "ws") + "/v1/ws", token, getToken: newToken });
      c.onEvent = onEvent;
      c.playout = p;
      await c.connect();
      if (stale()) throw new Error("closed");
      client = c;
      playout = p;
      setState("ready", "Ready. Tap the mic or type a question.");
    } catch (err) {
      c?.close(); // nothing half-open survives a failure or a close during connect
      p?.close();
      if (!stale()) {
        connecting = null;
        setState("error", err instanceof HumanCheckFailed ? "Couldn't verify you're human. Reload and try again."
          : `Could not connect: ${err instanceof Error ? err.message : err}`);
      }
      throw err;
    }
  })());

  const end = () => { // session cleanup: mic off, audio closed, socket closed, nothing carried into the next session
    epoch++;
    if (micOn) client?.stopMic();
    client?.close();
    playout?.close();
    client = playout = null;
    connecting = null;
    micOn = micBusy = false;
    sources.clear();
    partial = null;
    log.replaceChildren();
    mic.setAttribute("aria-pressed", "false");
    mic.innerHTML = ICON.mic;
  };

  launcher.addEventListener("click", () => {
    panel.hidden = false;
    launcher.hidden = true;
    launcher.setAttribute("aria-expanded", "true");
    mic.focus();
    void connect().catch(() => {});
  });
  close.addEventListener("click", () => {
    end();
    panel.hidden = true;
    launcher.hidden = false;
    launcher.setAttribute("aria-expanded", "false");
    launcher.focus();
  });
  mic.addEventListener("click", async () => {
    if (mic.hasAttribute("disabled") || micBusy) return;
    micBusy = true;
    try {
      await connect();
      if (micOn) {
        client!.stopMic();
        micOn = false;
        setState("ready", "Microphone off. You can type instead.");
      } else {
        await client!.startMic();
        micOn = true;
        setState("listening", "Listening… ask your question.");
      }
      mic.setAttribute("aria-pressed", String(micOn));
      mic.setAttribute("aria-label", micOn ? "Stop talking" : "Start talking");
      mic.innerHTML = micOn ? ICON.stop : ICON.mic;
    } catch (err) {
      const denied = err instanceof DOMException && (err.name === "NotAllowedError" || err.name === "SecurityError");
      if (denied) {
        mic.setAttribute("disabled", "");
        mic.setAttribute("aria-label", "Microphone blocked");
        setState("no-mic", "Microphone access was blocked. You can still type your question below.");
        input.focus();
      }
    } finally {
      micBusy = false;
    }
  });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    say("user", text);
    try {
      await connect();
      client!.send({ type: "text.input", text });
      setState("thinking", "Thinking…");
    } catch { /* status already explains */ }
  });
  addEventListener("pagehide", end);
}

if (document.body) mount();
else addEventListener("DOMContentLoaded", mount);
