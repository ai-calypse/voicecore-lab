# Diagrams

Each diagram is stored four ways:
- `.mmd` is the Mermaid source, the one to edit;
- `.png` is used in the docs;
- `.svg` is a vector copy;
- `.excalidraw` can be opened and moved around at excalidraw.com (File → Open).

| Diagram | Shows | Used in |
|---|---|---|
| [system-overview](system-overview.png) | the three programs, the rented models and the budget ledger | README, architecture |
| [voice-turn](voice-turn.png) | one spoken question, stage by stage, with live medians | README, architecture |
| [audio-journey](audio-journey.png) | the sound itself, from microphone to speaker | architecture |
| [barge-in](barge-in.png) | how an interruption silences every hop | architecture |
| [answer-pipeline](answer-pipeline.png) | ingest, hybrid search, the citation filter | architecture |
| [session-security](session-security.png) | tokens, the human check, resume keys | architecture |
| [scale-topology](scale-topology.png) | two gateways, two orchestrators, nginx and Redis | architecture |
| [observability](observability.png) | traces, metrics, logs, alerts | architecture |
| [ci-pipeline](ci-pipeline.png) | what CI runs on every push | architecture |

After editing a `.mmd` file, re-render the other three files with the gstack `/diagram` skill. A plain Mermaid renderer also works for the `.svg` and `.png` (for example `npx @mermaid-js/mermaid-cli -i x.mmd -o x.svg`).
