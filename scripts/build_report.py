"""Render the Phase 2 performance & reliability charts.

Consumes data/rtt_metrics.csv produced by scripts/rtt_probe.py and
emits a few PNG charts under docs/figures/:

    rtt_histogram.png        distribution of all RTT samples
    rtt_by_protocol.png      median + whiskers per protocol
    rtt_percentiles.png      p50/p90/p95/p99 bars
    rtt_table.md             markdown summary table (embedded in report)

The build_report.py is intentionally stdlib + matplotlib only — no
pandas, so the script is trivial to audit and works inside the
project's existing venv.
"""

import csv
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "rtt_metrics.csv"
FIG_DIR = ROOT / "docs" / "figures"


def load():
    rows = []
    with CSV_PATH.open() as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(
                {
                    "wall_ts": float(r["wall_ts"]),
                    "protocol": r["protocol"],
                    "room_key": r["room_key"],
                    "rtt_ms": float(r["rtt_ms"]),
                }
            )
    return rows


def percentile(values, pct):
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[k]


def render_histogram(rows):
    fig, ax = plt.subplots(figsize=(7, 4))
    all_rtts = [r["rtt_ms"] for r in rows]
    ax.hist(all_rtts, bins=30, color="#2277cc", edgecolor="white")
    ax.axvline(500, color="red", linestyle="--", label="500 ms target")
    ax.set_xlabel("Round-trip latency (ms)")
    ax.set_ylabel("Sample count")
    ax.set_title(f"RTT distribution (n = {len(all_rtts)})")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "rtt_histogram.png", dpi=150)
    plt.close(fig)


def render_by_protocol(rows):
    by_p = {}
    for r in rows:
        by_p.setdefault(r["protocol"], []).append(r["rtt_ms"])
    protocols = sorted(by_p.keys())
    data = [by_p[p] for p in protocols]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.boxplot(
        data,
        labels=[f"{p}\n(n={len(by_p[p])})" for p in protocols],
        showmeans=True,
        showfliers=False,
    )
    ax.axhline(500, color="red", linestyle="--", alpha=0.4, label="500 ms target")
    ax.set_ylabel("Round-trip latency (ms)")
    ax.set_title("RTT by protocol")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "rtt_by_protocol.png", dpi=150)
    plt.close(fig)


def render_percentiles(rows):
    all_rtts = [r["rtt_ms"] for r in rows]
    levels = [50, 75, 90, 95, 99]
    vals = [percentile(all_rtts, p) for p in levels]

    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar([f"p{p}" for p in levels], vals, color="#2288aa")
    for bar, v in zip(bars, vals):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(vals) * 0.01,
            f"{v:.1f} ms",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.axhline(500, color="red", linestyle="--", alpha=0.5, label="500 ms target")
    ax.set_ylabel("Round-trip latency (ms)")
    ax.set_title("RTT percentiles")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "rtt_percentiles.png", dpi=150)
    plt.close(fig)


def render_table(rows):
    by_p = {}
    for r in rows:
        by_p.setdefault(r["protocol"], []).append(r["rtt_ms"])
    all_rtts = [r["rtt_ms"] for r in rows]

    def stats(arr):
        if not arr:
            return "-", "-", "-", "-", "-"
        return (
            f"{len(arr)}",
            f"{min(arr):.2f}",
            f"{statistics.median(arr):.2f}",
            f"{percentile(arr, 95):.2f}",
            f"{max(arr):.2f}",
        )

    lines = [
        "| Segment | Samples | Min (ms) | Median (ms) | p95 (ms) | Max (ms) |",
        "|---|---|---|---|---|---|",
    ]
    for p in sorted(by_p.keys()):
        n, mn, md, p95, mx = stats(by_p[p])
        lines.append(f"| {p.upper()} | {n} | {mn} | {md} | {p95} | {mx} |")
    n, mn, md, p95, mx = stats(all_rtts)
    lines.append(f"| **ALL** | **{n}** | **{mn}** | **{md}** | **{p95}** | **{mx}** |")

    (FIG_DIR / "rtt_table.md").write_text("\n".join(lines) + "\n")


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    rows = load()
    if not rows:
        print("no samples in CSV; run scripts/rtt_probe.py first")
        return
    print(f"loaded {len(rows)} RTT samples")
    render_histogram(rows)
    render_by_protocol(rows)
    render_percentiles(rows)
    render_table(rows)
    print(f"wrote charts + table to {FIG_DIR}")


if __name__ == "__main__":
    main()
