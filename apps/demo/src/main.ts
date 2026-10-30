import { startPlayout, VoiceClient } from "@voicecore/web-sdk";

// Exposed for end-to-end tests and manual poking from the console.
(window as unknown as { voicecore: unknown }).voicecore = { VoiceClient, startPlayout };

const params = new URLSearchParams(location.search);
if (params.get("lab") !== "1" && document.querySelector("[data-landing]")) {
  // the landing page embeds the widget the same way any site would (the lab page does not)
  const s = document.createElement("script");
  s.src = "/embed/voicecore.js";
  s.dataset.endpoint = import.meta.env.VITE_GATEWAY ?? "http://localhost:8080";
  document.body.append(s);
}
if (params.get("lab") === "1") {
  void (async () => {
    const [{ renderLab }] = await Promise.all([import("./lab.ts"), import("./lab.css")]);
    document.title = "VoiceCore Lab · timeline";
    document.querySelector("[data-landing]")?.remove();
    const root = document.createElement("main");
    document.body.append(root);
    const show = (t: Parameters<typeof renderLab>[1]) => renderLab(root, t, show); // throws on a non-timeline; the caller reports it
    try {
      const res = await fetch(params.get("trace") ?? "/lab/sample-timeline.json");
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      show(await res.json());
    } catch (err) {
      root.className = "lab";
      root.textContent = `Could not load the trace (${String(err)}). Use ?trace=<url> or load a timeline JSON file.`;
    }
  })();
}
