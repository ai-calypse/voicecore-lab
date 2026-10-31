// Results at a glance: the final numbers from reports/, for readers who want the outcome before the method.
// Every value here is copied from a report and keeps its label: live (real providers) or mock (scripted ones).
// This page is outside docs/, so the voice assistant does not index it.
import React from "react";
import Layout from "@theme/Layout";
import Link from "@docusaurus/Link";
import styles from "./results.module.css";

const REPO = "https://github.com/ai-calypse/voicecore-lab/blob/main/";

// End of the question to the first sound of the answer, medians (reports/latency_tuning.md, latency_breakdown.md).
const COMPARE = [
  { name: "VoiceCore", ms: 841, note: "live, 15 spoken questions", accent: true },
  { name: "Deepgram's hosted Voice Agent", ms: 972, note: "live, 3 turns, not matched conditions" },
  { name: "VoiceCore's first live build", ms: 2317, note: "live, 15 spoken questions" },
];

// Where the time goes: stage medians of the same 15 turns (reports/latency_tuning.md). Medians do not add up exactly.
const STAGES = [
  { name: "Know you have finished speaking", ms: 340, note: "eager endpoint" },
  { name: "Language model's first word", ms: 340, note: "gpt-oss-120b on Cerebras" },
  { name: "First audio from text-to-speech", ms: 145, note: "pre-opened connection" },
  { name: "Network and playback", ms: 26, note: "gateway and browser" },
];

const GROUPS = [
  {
    title: "Speed",
    tiles: [
      { value: "340 ms", label: "to know you have finished speaking", detail: "median of 15 live turns", tag: "live", report: "reports/latency_tuning.md" },
      { value: "303 ms", label: "to go silent when you interrupt", detail: "8 of 8 interruptions silenced", tag: "live", report: "reports/barge_in.md" },
      { value: "0.19 ms", label: "added by the gateway per round trip", detail: "median of 500 frames, loopback", tag: "benchmark", report: "benchmarks/transport.md" },
    ],
  },
  {
    title: "Answer quality",
    tiles: [
      { value: "14 / 15", label: "right call to answer or decline", detail: "held-out questions it never saw while tuning", tag: "live", report: "reports/docs_eval.md" },
      { value: "12 / 12", label: "citations that support the answer", detail: "every sentence must cite a docs passage", tag: "live", report: "reports/docs_eval.md" },
      { value: "0", label: "claims leaked from poisoned pages", detail: "stale, contradicting and prompt-injected pages; 14 of 15 cases pass", tag: "live", report: "reports/docs_eval.md" },
      { value: "6.5 %", label: "speech-to-text word error rate", detail: "25 held-out clips, including noisy and slow speech", tag: "live", report: "reports/quality_eval.md" },
    ],
  },
  {
    title: "Reliability and scale",
    tiles: [
      { value: "50", label: "voice sessions at once on one orchestrator", detail: "event-loop lag p99 4.8 ms; two copies for 100", tag: "mock", report: "reports/load.md" },
      { value: "1,390", label: "sessions in a 30-minute soak test", detail: "no failed round; memory growth under 5 % per process", tag: "mock", report: "reports/load.md#soak" },
      { value: "0 / 4", label: "false interruptions from its own echo", detail: "the agent's voice leaking back into the mic", tag: "live", report: "reports/barge_in.md" },
    ],
  },
  {
    title: "Engineering",
    tiles: [
      { value: "~370", label: "automated tests in Go, Python and TypeScript", detail: "plus a CI gate that fails on slower or worse answers", tag: "ci", report: ".github/workflows" },
      { value: "$1.20", label: "model spend to build and measure everything", detail: "enforced by its own budget ledger", tag: "ledger", report: "benchmarks/spend_ledger.json" },
      { value: "3", label: "programs speaking one wire protocol", detail: "browser SDK, Go gateway, Python orchestrator", tag: "code", report: "packages/protocol/SPEC.md" },
    ],
  },
];

const TAG_TEXT = { live: "Live", mock: "Mock", benchmark: "Benchmark", ci: "CI", ledger: "Ledger", code: "Code" };

function Bars({ rows, max, caption, label }) {
  return (
    <figure className={styles.chart}>
      <figcaption className={styles.chartTitle}>{caption}</figcaption>
      <ul className={styles.bars} aria-label={label}>
        {rows.map((r) => (
          <li key={r.name} className={styles.barRow} tabIndex={0}>
            <span className={styles.barName}>{r.name}</span>
            <span className={styles.barTrack}>
              <span className={r.accent === false ? styles.barMuted : styles.bar} style={{ "--w": r.ms / max }} />
              <span className={styles.barValue}>{r.ms.toLocaleString("en-US")} ms</span>
            </span>
            <span className={styles.tooltip} role="tooltip">{r.name}: {r.ms.toLocaleString("en-US")} ms ({r.note})</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}

export default function Results() {
  return (
    <Layout title="Results" description="VoiceCore's measured results: response time, interruption, answer quality, scale and cost.">
      <main className={styles.page}>
        <header className={styles.hero}>
          <p className={styles.eyebrow}>Results</p>
          <p className={styles.heroValue}>841 ms</p>
          <p className={styles.heroLabel}>from the moment you stop talking to the first sound of the answer</p>
          <ul className={styles.heroFacts}>
            <li><strong>2.8× faster</strong> than the first live build</li>
            <li><strong>Faster</strong> than Deepgram's hosted Voice Agent in our test (972 ms)</li>
            <li><strong>13 of 15</strong> turns under one second</li>
          </ul>
          <p className={styles.heroNote}>Median of 15 spoken questions, real providers over a home network.</p>
        </header>

        <section className={styles.charts}>
          <Bars
            caption="Response time, median"
            label="End of question to first audio, median, in milliseconds"
            max={2317}
            rows={COMPARE.map((r) => ({ ...r, accent: !!r.accent }))}
          />
          <Bars
            caption="Where VoiceCore's time goes, stage medians"
            label="Stage medians of one voice turn, in milliseconds"
            max={340}
            rows={STAGES}
          />
        </section>

        {GROUPS.map((g) => (
          <section key={g.title} className={styles.group}>
            <h2 className={styles.groupTitle}>{g.title}</h2>
            <div className={styles.tiles}>
              {g.tiles.map((t) => (
                <a key={t.label} className={styles.tile} href={REPO + t.report}>
                  <span className={`${styles.tag} ${styles[`tag_${t.tag}`] ?? ""}`}>{TAG_TEXT[t.tag]}</span>
                  <span className={styles.tileValue}>{t.value}</span>
                  <span className={styles.tileLabel}>{t.label}</span>
                  <span className={styles.tileDetail}>{t.detail}</span>
                </a>
              ))}
            </div>
          </section>
        ))}

        <footer className={styles.method}>
          <p>
            <strong>Live</strong> means real providers (Deepgram for speech, gpt-oss-120b for answers) over a home
            network, with every process on one Apple M4 laptop. <strong>Mock</strong> means scripted providers, so
            the test measures VoiceCore itself. Samples are small, so the numbers compare designs; they are not
            production rates.
          </p>
          <p>
            Every card links to the report with the command that produced it. For how each stage works, start with{" "}
            <Link to="/concepts/latency">latency</Link> or <Link to="/concepts/how-a-voice-agent-works">how a voice agent works</Link>.
          </p>
        </footer>
      </main>
    </Layout>
  );
}
