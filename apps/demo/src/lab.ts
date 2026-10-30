// ?lab=1: one session's merged trace (harness/session_timeline.py output) as stage bars, speaking lanes and events.

type TraceEvent = {
  process: string; span: string; event: string; t_us: number;
  generation_id?: number; attrs: Record<string, unknown>;
};
export type Timeline = {
  session_id: string; reference_clock: string; label?: string;
  offsets_us?: Record<string, number>; gateway_counters?: Record<string, number>;
  events: TraceEvent[];
};

const STAGES = [
  { key: "endpoint", name: "Endpoint wait", hint: "trailing silence before the turn ended" },
  { key: "stt", name: "STT", hint: "endpoint to final transcript" },
  { key: "llm", name: "LLM first token", hint: "request to first token" },
  { key: "tts", name: "TTS first audio", hint: "first token to first audio" },
  { key: "playout", name: "Playout start", hint: "first audio to first sample rendered" },
] as const;

type Bar = { stage: (typeof STAGES)[number]["key"]; gen: number; from: number; to: number };
type Segment = { lane: "user" | "agent"; from: number; to: number; gen?: number; interrupted?: boolean };

const SVG = "http://www.w3.org/2000/svg";
const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
const svg = (tag: string, attrs: Record<string, string | number>, text?: string) => {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text !== undefined) e.textContent = text;
  return e;
};
const fmt = (ms: number | null | undefined) => (ms === null || ms === undefined ? "—" : `${Math.round(ms).toLocaleString()} ms`);

export function analyse(t: Timeline) {
  const ev = t.events;
  const is = (process: string, event: string) => (e: TraceEvent) => e.process === process && e.event === event;
  const gens = [...new Set(ev.filter(is("agent-core", "request")).map((e) => e.generation_id!))].sort((a, b) => a - b);
  const bars: Bar[] = [];
  const turns: { gen: number; speechEnd?: number; started?: number }[] = [];
  let prevReq = -Infinity;
  for (const g of gens) {
    const req = ev.find((e) => is("agent-core", "request")(e) && e.generation_id === g)!;
    const ft = ev.find((e) => is("agent-core", "first_token")(e) && e.generation_id === g);
    const fa = ev.find((e) => is("agent-core", "first_audio")(e) && e.generation_id === g);
    const ps = ev.find((e) => is("client", "playout.started")(e) && e.generation_id === g && e.attrs.dir === "out");
    const before = (name: string) => ev.filter((e) => is("agent-core", name)(e) && e.t_us > prevReq && e.t_us <= req.t_us).at(-1);
    const ep = before("endpoint"), tt = before("turn_text");
    const speechEnd = ep ? ep.t_us - Number(ep.attrs.silence_ms ?? 0) * 1000 : undefined;
    if (ep && speechEnd !== undefined) bars.push({ stage: "endpoint", gen: g, from: speechEnd, to: ep.t_us });
    if (ep && tt) bars.push({ stage: "stt", gen: g, from: ep.t_us, to: tt.t_us });
    if (ft) bars.push({ stage: "llm", gen: g, from: req.t_us, to: ft.t_us });
    if (ft && fa) bars.push({ stage: "tts", gen: g, from: ft.t_us, to: fa.t_us });
    if (fa && ps) bars.push({ stage: "playout", gen: g, from: fa.t_us, to: ps.t_us });
    turns.push({ gen: g, speechEnd, started: ps?.t_us });
    prevReq = req.t_us;
  }

  const segments: Segment[] = [];
  let userStart: number | undefined;
  for (const e of ev) {
    if (e.process !== "agent-core") continue;
    if (e.event === "speech_started" || e.event === "barge_in") userStart = e.t_us;
    if (e.event === "endpoint" && userStart !== undefined) {
      segments.push({ lane: "user", from: userStart, to: e.t_us - Number(e.attrs.silence_ms ?? 0) * 1000 });
      userStart = undefined;
    }
  }
  const cancelled = new Set(ev.filter(is("client", "agent.cancel")).map((e) => e.generation_id));
  for (const s of ev.filter((e) => is("client", "playout.started")(e) && e.attrs.dir === "out")) {
    const stop = ev.find((e) => is("client", "playout.stopped")(e) && e.attrs.dir === "out" && e.generation_id === s.generation_id);
    segments.push({ lane: "agent", gen: s.generation_id, from: s.t_us, to: stop?.t_us ?? ev.at(-1)!.t_us,
      interrupted: stop?.attrs.reason === "cancel" || cancelled.has(s.generation_id) });
  }

  const complete = turns.filter((x) => x.speechEnd !== undefined && x.started !== undefined).at(-1);
  const onset = ev.find((e) => e.event === "user.onset")?.attrs.onset_us as number | undefined;
  const cancelStop = ev.find((e) => is("client", "playout.stopped")(e) && e.attrs.reason === "cancel");
  const stageOf = (k: Bar["stage"]) => bars.filter((b) => b.stage === k).at(-1);
  const dur = (b?: Bar) => (b ? (b.to - b.from) / 1000 : null);
  return {
    gens, bars, segments,
    summary: {
      turn: complete ? (complete.started! - complete.speechEnd!) / 1000 : null,
      endpoint: dur(stageOf("endpoint")), llm: dur(stageOf("llm")), tts: dur(stageOf("tts")),
      interrupt: onset !== undefined && cancelStop ? (cancelStop.t_us - onset) / 1000 : null,
      interrupted: segments.filter((s) => s.interrupted).length,
    },
  };
}

export function renderLab(root: HTMLElement, t: Timeline, onLoad: (t: Timeline) => void) {
  const a = analyse(t);
  root.replaceChildren();
  root.className = "lab";

  const head = el("header", "lab-head");
  const title = el("div", "lab-title");
  title.append(el("h1", "", "Session timeline"), el("p", "lab-sub", `${t.session_id} · reference clock: ${t.reference_clock}${t.label ? ` · ${t.label}` : ""}`));
  const load = el("label", "lab-load");
  const input = el("input");
  input.type = "file";
  input.accept = "application/json,.json";
  input.addEventListener("change", async () => {
    const f = input.files?.[0];
    if (f) onLoad(JSON.parse(await f.text()) as Timeline);
  });
  load.append("Load trace…", input);
  head.append(title, load);

  const c = t.gateway_counters ?? {};
  const drops = Object.entries(c).filter(([k]) => k.startsWith("drops")).reduce((s, [, v]) => s + v, 0);
  const stats: [string, string, string][] = [
    ["Speech end → first audio", fmt(a.summary.turn), "last voice turn"],
    ["Endpoint wait", fmt(a.summary.endpoint), "silence before deciding"],
    ["LLM first token", fmt(a.summary.llm), "last generation"],
    ["TTS first audio", fmt(a.summary.tts), "after first token"],
    ["Interrupt → silence", fmt(a.summary.interrupt), `${a.summary.interrupted} interrupted`],
    ["Gateway drops · gaps", t.gateway_counters ? `${drops} · ${c.gaps ?? 0}` : "—", "all sessions"],
  ];
  const strip = el("dl", "lab-stats");
  for (const [k, v, n] of stats) {
    const d = el("div", "stat");
    d.append(el("dt", "", k), el("dd", "", v), el("span", "stat-note", n));
    strip.append(d);
  }

  const chart = el("section", "lab-chart");
  chart.setAttribute("aria-label", "Timeline");
  const draw = () => drawChart(chart, t, a);
  new ResizeObserver(draw).observe(chart);

  const table = eventsTable(t);
  root.append(head, strip, chart, table);
  draw();
}

function drawChart(host: HTMLElement, t: Timeline, a: ReturnType<typeof analyse>) {
  const t0 = t.events[0]!.t_us, t1 = t.events.at(-1)!.t_us;
  const W = Math.max(host.clientWidth, 720), LABEL = 132, PAD = 16, ROW = 26;
  const x = (us: number) => LABEL + ((us - t0) / (t1 - t0)) * (W - LABEL - PAD);
  const rows = [{ key: "user", name: "User speaking" }, { key: "agent", name: "Agent speaking" }, ...STAGES.map((s) => ({ key: s.key, name: s.name }))];
  const H = 28 + rows.length * ROW + 12;
  const root = svg("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Speaking lanes and stage bars over time" });
  root.append(Object.assign(svg("defs", {}), { innerHTML: `<pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" class="hatch-bg"/><line x1="0" y1="0" x2="0" y2="6" class="hatch-line"/></pattern>` }));

  const span = (t1 - t0) / 1000, step = [100, 250, 500, 1000, 2000, 5000, 10000].find((s) => span / s <= 10) ?? 20000;
  for (let ms = 0; ms <= span; ms += step) {
    const xx = x(t0 + ms * 1000);
    root.append(svg("line", { x1: xx, x2: xx, y1: 20, y2: H - 8, class: "grid" }), svg("text", { x: xx, y: 13, class: "tick", "text-anchor": "middle" }, ms >= 1000 ? `${ms / 1000} s` : `${ms} ms`));
  }
  rows.forEach((r, i) => {
    const y = 28 + i * ROW;
    const g = svg("g", { "data-row": r.key, ...(STAGES.some((s) => s.key === r.key) ? { "data-stage": r.key } : {}) });
    g.append(svg("text", { x: 0, y: y + 13, class: "row-label" }, r.name));
    if (i === 2) root.append(svg("line", { x1: 0, x2: W, y1: y - 5, y2: y - 5, class: "divider" }));
    root.append(g);
  });
  const rowY = (key: string) => 28 + rows.findIndex((r) => r.key === key) * ROW;
  const group = (key: string) => root.querySelector(`[data-row="${key}"]`)!;

  for (const s of a.segments) {
    const y = rowY(s.lane), w = Math.max(2, x(s.to) - x(s.from));
    const g = svg("g", { class: `seg ${s.lane}${s.interrupted ? " interrupted" : ""}`, ...(s.gen ? { "data-gen": s.gen } : {}), "data-interrupted": String(!!s.interrupted) });
    g.append(svg("rect", { x: x(s.from), y: y + 3, width: w, height: ROW - 10, rx: 3 }));
    if (s.lane === "agent") g.append(svg("text", { x: x(s.from) + 6, y: y + 15, class: "seg-label" }, `gen ${s.gen}${s.interrupted ? " · interrupted" : ""}`));
    if (s.interrupted) g.append(svg("rect", { x: x(s.to) - 3, y: y + 1, width: 3, height: ROW - 6, class: "cut" }));
    const tip = svg("title", {}, `${s.lane === "user" ? "User speech" : `Generation ${s.gen}`}: ${fmt((s.to - s.from) / 1000)}${s.interrupted ? ", cancelled by barge-in" : ""}`);
    g.append(tip);
    group(s.lane).append(g);
  }
  for (const b of a.bars) {
    const y = rowY(b.stage), w = Math.max(2, x(b.to) - x(b.from));
    const g = svg("g", { class: `bar ${b.stage}`, "data-gen": b.gen });
    g.append(svg("rect", { x: x(b.from), y: y + 5, width: w, height: ROW - 14, rx: 2 }), svg("title", {}, `${STAGES.find((s) => s.key === b.stage)!.name}, gen ${b.gen}: ${fmt((b.to - b.from) / 1000)}`));
    g.append(svg("text", { x: x(b.to) + 4, y: y + 15, class: "bar-label" }, fmt((b.to - b.from) / 1000)));
    group(b.stage).append(g);
  }
  host.replaceChildren(root);
}

function eventsTable(t: Timeline) {
  const sec = el("section", "lab-events");
  const bar = el("div", "lab-events-head");
  bar.append(el("h2", "", "Events"));
  const procs = [...new Set(t.events.map((e) => e.process))];
  const shown = new Set(procs);
  const chips = el("div", "chips");
  chips.setAttribute("role", "group");
  chips.setAttribute("aria-label", "Show processes");
  const tbody = el("tbody");
  const fill = () => {
    tbody.replaceChildren();
    const t0 = t.events[0]!.t_us;
    for (const e of t.events) {
      if (!shown.has(e.process)) continue;
      const tr = el("tr");
      const details = Object.entries(e.attrs).filter(([k, v]) => v !== null && k !== "dir").map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(" ");
      tr.append(el("td", "num", ((e.t_us - t0) / 1000).toFixed(1)), el("td", `proc ${e.process}`, e.process), el("td", "code", `${e.span}.${e.event}`),
        el("td", "num", e.generation_id ? String(e.generation_id) : ""), el("td", "code details", details));
      tbody.append(tr);
    }
  };
  for (const p of procs) {
    const b = el("button", "chip", p);
    b.type = "button";
    b.setAttribute("aria-pressed", "true");
    b.addEventListener("click", () => {
      if (shown.has(p)) shown.delete(p); else shown.add(p);
      b.setAttribute("aria-pressed", String(shown.has(p)));
      fill();
    });
    chips.append(b);
  }
  bar.append(chips);
  const wrap = el("div", "table-wrap");
  const table = el("table");
  const head = el("thead");
  const hr = el("tr");
  for (const h of ["ms", "process", "event", "gen", "details"]) hr.append(el("th", h === "ms" || h === "gen" ? "num" : "", h));
  head.append(hr);
  table.append(head, tbody);
  wrap.append(table);
  sec.append(bar, wrap);
  fill();
  return sec;
}
