"""Latency chart for the README (S08-T03): uv run python harness/latency_chart.py

Stage medians of one voice turn (speech end -> first agent audio rendered) from three recorded runs.
Writes reports/latency_chart_{light,dark}.png. Numbers come from each run's latency.json; the asr_assisted
first segment is the derived speech end -> LLM request median (reports/perf.md), because its asr-triggered
endpoints carry no frame time. Stage medians do not add up exactly to the total median printed at the bar end.
"""
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from fixtures import ROOT  # noqa: E402

RAW = ROOT / "benchmarks/raw"
STAGES = ["Turn end detected (endpoint + STT)", "LLM first token", "TTS first audio", "Transport + playout start (10-16 ms)"]
# reference categorical palette (dataviz skill), slots 1-4, validated for each surface
THEMES = {
    "light": {"bg": "#ffffff", "ink": "#1f2328", "muted": "#59636e", "grid": "#d1d9e0", "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]},
    "dark": {"bg": "#0d1117", "ink": "#f0f6fc", "muted": "#9198a1", "grid": "#3d444d", "series": ["#3987e5", "#d95926", "#199e70", "#c98500"]},
}


def stages(run, first=None):
    s = json.loads((RAW / run / "latency.json").read_text())["summary"]
    p = {k: v["p50"] for k, v in s.items() if isinstance(v, dict)}
    turn_end = first if first is not None else p["endpoint_delay_ms"] + p["stt_settle_ms"]
    return [turn_end, p["llm_first_token_ms"], p["tts_first_audio_ms"], p["residual_ms"]], p["total_ms"]


ROWS = [
    ("Live, fixed 800 ms endpoint (n = 15)", *stages("wss_live_fixed_20261030T020448Z")),
    ("Live, ASR-assisted endpoint (n = 12)", *stages("wss_live_asr_assisted_20261030T020917Z", first=523.4)),
    ("Mock providers, 40 sessions (n = 40)", *stages("wss_mock_fixed_20261030T022315Z")),
]


def draw(theme: str):
    t = THEMES[theme]
    fig, ax = plt.subplots(figsize=(10, 3.6), dpi=150)
    fig.patch.set_facecolor(t["bg"])
    ax.set_facecolor(t["bg"])
    for y, (label, segs, total) in enumerate(ROWS):
        left = 0.0
        for i, ms in enumerate(segs):
            ax.barh(y, ms, left=left, height=0.55, color=t["series"][i], edgecolor=t["bg"], linewidth=2)  # 2px surface gap
            if ms >= 120:  # direct label only where it fits
                ax.text(left + ms / 2, y, f"{ms:,.0f}", ha="center", va="center", fontsize=9, color="#ffffff" if i in (0, 1) else "#1f2328")
            left += ms
        ax.text(left + 40, y, f"{total:,.0f} ms total (p50)", va="center", fontsize=9.5, color=t["ink"])
    ax.set_yticks(range(len(ROWS)), [r[0] for r in ROWS], color=t["ink"], fontsize=10)
    ax.invert_yaxis()
    ax.set_xlim(0, 3200)
    ax.set_xlabel("ms from the end of the user's speech (stage medians)", color=t["muted"], fontsize=9.5)
    ax.tick_params(axis="x", colors=t["muted"], labelsize=9)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=t["grid"], linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ax.spines.values():
        side.set_visible(False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in t["series"]]
    leg = ax.legend(handles, STAGES, ncol=2, loc="lower left", bbox_to_anchor=(0, 1.02), frameon=False, fontsize=9, handlelength=1.2)
    for txt in leg.get_texts():
        txt.set_color(t["ink"])
    fig.tight_layout()
    fig.savefig(ROOT / f"reports/latency_chart_{theme}.png", facecolor=t["bg"], bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


if __name__ == "__main__":
    for theme in THEMES:
        draw(theme)
    print("reports/latency_chart_light.png", "reports/latency_chart_dark.png")
