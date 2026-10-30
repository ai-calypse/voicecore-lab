// Page ids are file paths under docs/ without ".md".
module.exports = {
  docs: [
    { type: "category", label: "Getting started", collapsed: false, items: ["intro", "getting-started/quickstart", "getting-started/live-providers", "getting-started/embed-the-widget"] },
    {
      type: "category",
      label: "Concepts",
      collapsed: false,
      items: [
        "concepts/how-a-voice-agent-works",
        "concepts/latency",
        "concepts/turn-taking",
        "concepts/endpointing",
        "concepts/barge-in-and-echo",
        "concepts/generations-and-cancellation",
        "concepts/grounded-answers",
      ],
    },
    {
      type: "category",
      label: "Architecture",
      collapsed: false,
      items: ["architecture/overview", "architecture/browser-sdk", "architecture/realtime-gateway", "architecture/orchestrator", "architecture/websocket-vs-webrtc"],
    },
    {
      type: "category",
      label: "Guides",
      collapsed: false,
      items: ["guides/measure-latency", "guides/tune-latency", "guides/add-your-own-docs", "guides/telephony", "guides/troubleshooting"],
    },
    {
      type: "category",
      label: "Reference",
      collapsed: false,
      items: ["reference/wire-protocol", "reference/configuration", "reference/trace-events", "reference/providers", "reference/benchmarks", "faq"],
    },
  ],
};
