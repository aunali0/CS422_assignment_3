import csv
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from statistics import fmean, stdev
from textwrap import wrap

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from measurement import RunMetadata, Sample


type Run = tuple[RunMetadata, list[Sample]]


def values(samples: list[Sample], pick: Callable[[Sample], float | int | None]) -> list[float]:
    # Missing fields (older kernel, or no delta available) become NaN so matplotlib
    # leaves a gap instead of drawing a misleading zero.
    return [float("nan") if (value := pick(sample)) is None else float(value) for sample in samples]


def style_axes(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.25, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", labelsize=10)


def run_statistics(test, run: Run):
    meta, samples = run
    elapsed = sum(s.interval for s in samples)
    rtts = [s.rtt_ms() for s in samples if s.rtt_ms() is not None]
    return {
        "destination": meta.destination(),
        "algorithm": meta.algorithm,
        "repetition": test["repetition"],
        "run_id": meta.run_id,
        "goodput_weighted_mbps": sum(s.bytes_acked_delta for s in samples) * 8 / elapsed / 1e6,
        "rtt_mean_ms": fmean(rtts) if rtts else None,
        "retransmitted_segments": sum(s.retrans_delta or 0 for s in samples),
    }


def write_csv(path, rows):
    if not rows:
        path.unlink(missing_ok=True)
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def text_pages(pdf, title, paragraphs):
    lines = []
    for paragraph in paragraphs:
        if paragraph.startswith("#"):
            paragraph = paragraph.lstrip("#").strip()
        lines.extend(wrap(paragraph, 98) if paragraph else [""])
        lines.append("")
    for start in range(0, max(1, len(lines)), 34):
        fig = plt.figure(figsize=(11.7, 8.3))
        fig.text(0.06, 0.94, title, fontsize=16, weight="bold", va="top")
        fig.text(
            0.06,
            0.87,
            "\n".join(lines[start : start + 34]),
            fontsize=10,
            va="top",
            linespacing=1.35,
        )
        pdf.savefig(fig)
        plt.close(fig)


def matched_destinations(manifest, runs):
    expected = {
        (algorithm, repetition)
        for algorithm in manifest["algorithms"]
        for repetition in range(1, manifest["repetitions"] + 1)
    }
    matched = []
    for destination in manifest["selected_destinations"]:
        group = [
            (test, meta, samples)
            for test, (meta, samples) in runs
            if meta.destination() == destination
        ]
        keys = [(meta.algorithm, test["repetition"]) for test, meta, _ in group]
        if len(keys) != len(expected) or set(keys) != expected:
            continue
        if all(
            samples
            and test.get("status", "ok") == "ok"
            and meta.algorithm == test.get("requested_algorithm", meta.algorithm)
            and meta.algorithm == test.get("actual_algorithm", meta.algorithm)
            and meta.destination() == test.get("destination", meta.destination())
            and meta.duration == manifest["config"]["duration"]
            and meta.goodput_interval == manifest["config"]["goodput_interval"]
            for test, meta, samples in group
        ):
            matched.append(destination)
    return matched


def plot_comparison(runs, algorithms, destination, pdf, times_pdf, scatter_pdf):
    selected = [(test, run) for test, run in runs if run[0].destination() == destination]
    colors = {name: plt.get_cmap("tab10")(i % 10) for i, name in enumerate(algorithms)}
    metrics = [
        ("Congestion window (segments)", lambda s: s.info["snd_cwnd"]),
        ("RTT (ms)", lambda s: s.rtt_ms()),
        ("Retransmitted segments / interval", lambda s: s.retrans_delta),
        ("Goodput (Mbit/s)", lambda s: s.goodput),
    ]
    fig, axes = plt.subplots(
        4,
        len(algorithms),
        squeeze=False,
        figsize=(5 * len(algorithms), 12),
        sharey="row",
        sharex=True,
        layout="constrained",
    )
    fig.suptitle(f"{destination} | matched settings; individual repetitions")
    for col, algorithm in enumerate(algorithms):
        axes[0, col].set_title(algorithm)
        for test, (meta, samples) in selected:
            if meta.algorithm != algorithm:
                continue
            for row, (label, pick) in enumerate(metrics):
                axes[row, col].plot(
                    [s.time for s in samples],
                    values(samples, pick),
                    color=colors[algorithm],
                    alpha=0.65,
                    linestyle=["-", "--", ":", "-."][(test["repetition"] - 1) % 4],
                    label=f"Run {test['repetition']}",
                )
                style_axes(axes[row, col])
        axes[0, col].legend(fontsize=8)
        axes[-1, col].set_xlabel("Time (s)")
    for ax in axes.flat:
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
    for row, (label, _) in enumerate(metrics):
        axes[row, 0].set_ylabel(label)
    fig.savefig(times_pdf, bbox_inches="tight", pad_inches=0.15)
    pdf.savefig(fig, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    fig, axes = plt.subplots(
        3,
        len(algorithms),
        squeeze=False,
        figsize=(5 * len(algorithms), 10),
        sharex="row",
        sharey=True,
        layout="constrained",
    )
    fig.suptitle(f"{destination} | all repetitions; common scales per metric")
    for col, algorithm in enumerate(algorithms):
        axes[0, col].set_title(algorithm)
        for test, (meta, samples) in selected:
            if meta.algorithm != algorithm:
                continue
            for row, (label, pick) in enumerate(metrics[:3]):
                axes[row, col].scatter(
                    values(samples, pick),
                    [s.goodput for s in samples],
                    s=10,
                    alpha=0.4,
                    color=colors[algorithm],
                    marker=["o", "x", "^", "s"][(test["repetition"] - 1) % 4],
                    label=f"Run {test['repetition']}",
                )
                axes[row, col].set_xlabel(label)
                style_axes(axes[row, col])
        axes[0, col].legend(fontsize=8)
    for ax in axes.flat:
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
    for ax in axes[:, 0]:
        ax.set_ylabel("Goodput (Mbit/s)")
    fig.savefig(scatter_pdf, bbox_inches="tight", pad_inches=0.15)
    pdf.savefig(fig, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def build_report(manifest, runs, out: Path):
    reports_dir = out / "reports"
    plots_dir = out / "plots"
    reports_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    matched = matched_destinations(manifest, runs)
    rows = [
        dict(run_statistics(test, run), matched_destination=run[0].destination() in matched)
        for test, run in runs
    ]
    write_csv(reports_dir / "per-test-statistics.csv", rows)
    groups = defaultdict(list)
    for row in rows:
        if row["matched_destination"]:
            groups[row["destination"], row["algorithm"]].append(row)
    aggregates = []
    for (destination, algorithm), group in groups.items():
        means = [r["goodput_weighted_mbps"] for r in group]
        rtts = [r["rtt_mean_ms"] for r in group if r["rtt_mean_ms"] is not None]
        aggregates.append(
            {
                "destination": destination,
                "algorithm": algorithm,
                "runs": len(group),
                "goodput_run_mean_mbps": fmean(means),
                "goodput_run_stddev_mbps": stdev(means) if len(means) > 1 else 0,
                "rtt_run_mean_ms": fmean(rtts) if rtts else None,
                "rtt_run_stddev_ms": stdev(rtts) if len(rtts) > 1 else 0,
            }
        )
    write_csv(reports_dir / "destination-algorithm-statistics.csv", aggregates)
    cfg = manifest["config"]
    paragraphs = [
        f"Completed matched destinations: {len(matched)}/{manifest['requested_destinations']}. "
        f"Algorithms: {', '.join(manifest['algorithms'])}. "
        f"Repetitions per algorithm: {manifest['repetitions']}. "
        f"Duration: {cfg['duration']} s. Sampling: {cfg['goodput_interval']} s. "
        f"Seed: {manifest['seed']}. Host kernel: {manifest['environment']['kernel']}.",
        f"Test order: {manifest['order_method']}. Exact order, settings, and failures are saved "
        "in manifest.json and experiment.log. Only complete groups with matching settings "
        "enter comparisons. Successful partial runs remain in per-test-statistics.csv.",
        "Per-run goodput uses acknowledged-byte differences divided by actual elapsed time. "
        "Throughput and RTT aggregates are the mean and sample standard deviation across runs. "
        "Per-run RTT is the mean sampled smoothed RTT. Retransmitted segments are a loss proxy, "
        "not an exact packet-loss probability.",
    ]
    if not matched:
        paragraphs.append("No complete matched destination is available. There is no measured "
                          "algorithm comparison to interpret yet.")
    excluded = set(manifest["selected_destinations"]) - set(matched)
    if excluded:
        paragraphs.append("Excluded incomplete or mismatched destination groups: "
                          + ", ".join(sorted(excluded)) + ". Check manifest.json and run metadata.")
    for destination in matched:
        for row in aggregates:
            if row["destination"] != destination:
                continue
            rtt = (f"{row['rtt_run_mean_ms']:.3f} ± {row['rtt_run_stddev_ms']:.3f} ms"
                   if row["rtt_run_mean_ms"] is not None else "unavailable")
            paragraphs.append(f"{destination} | {row['algorithm']} | {row['runs']} runs: "
                              f"goodput {row['goodput_run_mean_mbps']:.3f} ± "
                              f"{row['goodput_run_stddev_mbps']:.3f} Mbit/s; RTT {rtt}.")
    paragraphs += [
        "Limitations: sequential public-server tests cannot hold routes, cross-traffic, or "
        "server limits constant. Small differences relative to run variability do not establish "
        "an advantage. These single-flow tests do not establish fairness or convergence.",
        "AI assistance: we used AI tools to generate and revise the majority of the "
        "controller, loader, Python experiment code, tests, and plotting/reporting code, "
        "and to help refine the design, analysis, and explanations.",
    ]
    title = "Assignment 3: congestion control comparison"
    (reports_dir / "algorithm-comparison-report.md").write_text(
        "# " + title + "\n\n" + "\n\n".join(paragraphs) + "\n"
    )
    with PdfPages(reports_dir / "algorithm-comparison-report.pdf") as pdf:
        text_pages(pdf, title, paragraphs)
        for start in range(0, len(rows), 18):
            page_rows = rows[start:start + 18]
            fig, ax = plt.subplots(figsize=(15, 8), layout="constrained")
            ax.axis("off")
            ax.set_title("Per-run statistics; * = excluded destination group")
            table = ax.table(
                cellText=[[
                    row["destination"] + ("" if row["matched_destination"] else "*"),
                    row["algorithm"], row["repetition"], f"{row['goodput_weighted_mbps']:.3f}",
                    f"{row['rtt_mean_ms']:.3f}" if row["rtt_mean_ms"] is not None else "unavailable",
                    row["retransmitted_segments"],
                ] for row in page_rows],
                colLabels=["Destination", "Algorithm", "Run", "Goodput (Mbit/s)", "RTT (ms)", "Retransmits"],
                cellLoc="center", loc="center", colWidths=[.3, .12, .06, .18, .18, .16],
            )
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1, 1.6)
            pdf.savefig(fig)
            plt.close(fig)
        representative = manifest["representative"]
        if representative not in matched:
            representative = matched[0] if matched else None
        if representative in matched:
            plot_comparison(runs, manifest["algorithms"], representative, pdf,
                            plots_dir / "algorithm-metrics-over-time.pdf",
                            plots_dir / "algorithm-metrics-vs-goodput.pdf")
        else:
            (plots_dir / "algorithm-metrics-over-time.pdf").unlink(missing_ok=True)
            (plots_dir / "algorithm-metrics-vs-goodput.pdf").unlink(missing_ok=True)
