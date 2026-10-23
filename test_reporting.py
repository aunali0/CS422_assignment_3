import csv
import io
import json
import logging
import socket
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from client import ClientConfig, TestResult
from comparison import preflight, run_comparison
from comparison_plots import build_report, matched_destinations, plot_comparison
from measurement import RunMetadata, Sample
from tcp_info import TCP_INFO_FIELDS
from matplotlib.backends.backend_agg import FigureCanvasAgg
import matplotlib.pyplot as plt

ALGORITHMS = ["cubic", "reno", "bbr", "a3_cc"]
CFG = ClientConfig(10, 5, .2, 5, 3, 3)


def fixture(host="offline.invalid"):
    # Entirely synthetic: these numbers are for checking reports, not performance.
    runs = []
    for index, algorithm in enumerate(ALGORITHMS, 1):
        for repetition in range(1, 4):
            run_id = f"offline-fixture-{host}-{algorithm}-{repetition}"
            meta = RunMetadata(run_id, host, 5201, algorithm, CFG.duration,
                               CFG.goodput_interval, "offline", "offline", 232)
            samples = []
            elapsed = 0
            for number in range(50):
                interval = .1 if number == 0 else .3 if number == 1 else .2
                elapsed += interval
                rate = 10 * index + repetition + number % 2
                info = dict.fromkeys(name for name, _ in TCP_INFO_FIELDS)
                info.update(snd_cwnd=100 * index, snd_mss=1000,
                            rtt=10_000 * index + 1000 * repetition,
                            min_rtt=10_000, snd_ssthresh=2**31 - 1)
                samples.append(Sample(elapsed, interval, rate,
                                      round(rate * 1e6 / 8 * interval),
                                      0, info))
            test = {"destination": meta.destination(), "repetition": repetition,
                    "requested_algorithm": algorithm, "actual_algorithm": algorithm,
                    "status": "ok", "run_id": run_id}
            runs.append((test, (meta, samples)))
    return runs


def manifest_for(runs):
    destinations = list(dict.fromkeys(meta.destination() for _, (meta, _) in runs))
    return {"selected_destinations": destinations, "requested_destinations": len(destinations),
            "representative": destinations[0], "algorithms": ALGORITHMS, "repetitions": 3,
            "config": {"duration": CFG.duration, "goodput_interval": CFG.goodput_interval},
            "seed": 422, "environment": {"kernel": "offline"},
            "order_method": "offline fixture", "tests": [test for test, _ in runs]}


class ReportingTests(unittest.TestCase):
    def setUp(self):
        # Fail immediately if a check accidentally reaches real networking.
        for name in ("socket.socket", "socket.getaddrinfo"):
            patcher = patch(name, side_effect=AssertionError("Offline check attempted networking"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_four_algorithms_pass_unconnected_preflight(self):
        sock = MagicMock()
        sock.__enter__.return_value = sock
        with patch("comparison.platform.system", return_value="Linux"), patch(
            "comparison.socket.socket", return_value=sock
        ), patch("comparison.get_tcp_algorithm", side_effect=ALGORITHMS), patch(
            "comparison.get_tcp_info", return_value={name: 0 for name, _ in TCP_INFO_FIELDS}
        ):
            environment = preflight(ALGORITHMS)
        self.assertEqual(environment["algorithms"], dict(zip(ALGORITHMS, ALGORITHMS)))
        self.assertEqual([call.args[2] for call in sock.setsockopt.call_args_list],
                         [name.encode() for name in ALGORITHMS])
        sock.connect.assert_not_called()

    def test_only_complete_groups_with_matching_settings_are_retained(self):
        runs = fixture()
        manifest = manifest_for(runs)
        self.assertEqual(matched_destinations(manifest, runs), ["offline.invalid:5201"])
        cases = {"missing": runs[:-1], "duplicate": runs + [runs[0]]}
        test, (meta, samples) = runs[-1]
        for field, value in (("duration", 60), ("goodput_interval", 1), ("algorithm", "reno")):
            cases[field] = runs[:-1] + [(test, (replace(meta, **{field: value}), samples))]
        for field, value in (("requested_algorithm", "reno"), ("actual_algorithm", "reno"),
                             ("destination", "other.invalid:5201"), ("status", "failed")):
            cases[field] = runs[:-1] + [({**test, field: value}, (meta, samples))]
        for name, changed in cases.items():
            with self.subTest(name=name):
                self.assertEqual(matched_destinations(manifest, changed), [])

    def test_partial_destination_does_not_exclude_a_complete_destination(self):
        complete = fixture()
        partial = fixture("partial.invalid")[:-1]
        self.assertEqual(matched_destinations(manifest_for(complete + partial), complete + partial),
                         ["offline.invalid:5201"])

    def test_runner_and_saved_reports_include_all_four_and_preserve_failures(self):
        runs = fixture()
        calls = []
        figures = []
        original_close = plt.close

        def capture(fig):
            if hasattr(fig, "axes"):
                figures.append(fig)
            original_close(fig)

        def runner(host, port, cfg, run_id):
            calls.append((host, cfg))
            if len(calls) == 2:
                logging.error("Offline fixture: server rejected the test")
                return None
            repetition = int(run_id.rsplit("-", 2)[1].removeprefix("r"))
            meta, samples = next(run for test, run in runs
                                 if run[0].algorithm == cfg.algorithm
                                 and test["repetition"] == repetition)
            actual = "unexpected" if len(calls) == 3 else cfg.algorithm
            return TestResult(replace(meta, host=host, port=port, algorithm=actual,
                                      run_id=run_id), samples, 1)

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            servers = out / "servers.csv"
            servers.write_text("IP/HOST,PORT\nfirst.invalid,5201\nsecond.invalid,5201\n")
            args = Namespace(algorithms=ALGORITHMS, seed=422, servers=servers, count=1,
                             attempts=2, out_dir=out, repetitions=3, pause=.001)
            with patch("comparison.preflight", return_value={"kernel": "offline"}), patch(
                "comparison.try_run_test", side_effect=runner
            ), patch("comparison.time.sleep"), patch(
                "comparison_plots.plt.close", side_effect=capture
            ), redirect_stdout(io.StringIO()):
                self.assertTrue(run_comparison(args, CFG, "offline-fixture"))
            result = out / "algorithm-comparisons/offline-fixture"
            manifest = json.loads((result / "manifest.json").read_text())
            self.assertEqual(len(calls), 24)
            self.assertEqual(sum(test["status"] == "failed" for test in manifest["tests"]), 2)
            self.assertIn("Algorithm readback mismatch", {t.get("reason") for t in manifest["tests"]})
            self.assertIn("server rejected", (result / "experiment.log").read_text())
            retained = manifest["selected_destinations"][0]
            for host in {host for host, _ in calls}:
                self.assertEqual({cfg.algorithm for called_host, cfg in calls if host == called_host},
                                 set(ALGORITHMS))
            self.assertTrue(all(cfg.duration == 10 and cfg.goodput_interval == .2 for _, cfg in calls))
            self.assertEqual(CFG.algorithm, None)
            with (result / "reports/destination-algorithm-statistics.csv").open() as stream:
                aggregates = list(csv.DictReader(stream))
            self.assertEqual({row["algorithm"] for row in aggregates}, set(ALGORITHMS))
            self.assertTrue(all(row["destination"] == retained and row["runs"] == "3"
                                for row in aggregates))
            with (result / "reports/per-test-statistics.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 22)
            self.assertEqual(sum(row["matched_destination"] == "True" for row in rows), 12)
            _, samples = runs[0][1]
            expected = sum(s.bytes_acked_delta for s in samples) * 8e-6 / sum(s.interval for s in samples)
            cubic_rows = [row for row in rows if row["algorithm"] == "cubic"]
            self.assertTrue(all(abs(float(row["goodput_weighted_mbps"])
                                    - (expected + int(row["repetition"]) - 1)) < 1e-9
                                for row in cubic_rows))
            self.assertTrue(all("p95" not in key and "bdp" not in key for key in rows[0]))
            for row in aggregates:
                index = ALGORITHMS.index(row["algorithm"]) + 1
                self.assertAlmostEqual(float(row["goodput_run_mean_mbps"]), 10 * index + 2.51)
                self.assertAlmostEqual(float(row["goodput_run_stddev_mbps"]), 1)
                self.assertAlmostEqual(float(row["rtt_run_mean_ms"]),
                                       10 * index + 2)
                self.assertAlmostEqual(float(row["rtt_run_stddev_ms"]), 1)
            report = (result / "reports/algorithm-comparison-report.md").read_text()
            self.assertIn("cubic, reno, bbr, a3_cc", report)
            self.assertNotIn("Assignment 2 Q3", report)
            for name in ("reports/algorithm-comparison-report.pdf", "plots/algorithm-metrics-over-time.pdf",
                         "plots/algorithm-metrics-vs-goodput.pdf"):
                self.assertGreater((result / name).stat().st_size, 100)
            time = next(fig for fig in figures if len(fig.axes) == 16)
            self.assertEqual([ax.get_title() for ax in time.axes[:4]], ALGORITHMS)
            for ax in time.axes[:4]:
                self.assertEqual(len({line.get_color() for line in ax.lines}), 1)
                self.assertEqual({line.get_linestyle() for line in ax.lines}, {"-", "--", ":"})
                self.assertEqual({text.get_text() for text in ax.get_legend().get_texts()},
                                 {"Run 1", "Run 2", "Run 3"})
            self.assertEqual({path.name for path in (result / "plots").iterdir()},
                             {"algorithm-metrics-over-time.pdf", "algorithm-metrics-vs-goodput.pdf"})
            self.assertFalse(any((result / "tcp-traces").rglob("*.pdf")))
            self.assertFalse((result / "reports/reviewed-algorithm-comparison.pdf").exists())

    def test_fourth_algorithm_extremes_are_visible_on_common_axes(self):
        runs = fixture()
        changed = []
        for test, (meta, samples) in runs:
            if meta.algorithm == "a3_cc":
                samples = [replace(s, goodput=500,
                                   info={**s.info, "snd_cwnd": 50_000, "rtt": 200_000}) for s in samples]
            changed.append((test, (meta, samples)))
        figures = []
        original_close = plt.close

        def capture(fig):
            if hasattr(fig, "axes"):
                figures.append(fig)
            original_close(fig)

        with tempfile.TemporaryDirectory() as directory, patch(
            "comparison_plots.plt.close", side_effect=capture
        ):
            out = Path(directory)
            plot_comparison(changed, ALGORITHMS, "offline.invalid:5201", MagicMock(),
                            out / "time.pdf", out / "scatter.pdf")
        time, scatter = figures
        self.assertEqual(len(time.axes), 16)
        self.assertEqual(len(scatter.axes), 12)
        for fig in figures:
            self.assertEqual([ax.get_title() for ax in fig.axes[:4]], ALGORITHMS)
            for ax in fig.axes[:4]:
                self.assertEqual([text.get_text() for text in ax.get_legend().get_texts()],
                                 ["Run 1", "Run 2", "Run 3"])
            canvas = FigureCanvasAgg(fig)
            canvas.draw()
            renderer = canvas.get_renderer()
            for ax in fig.axes:
                for artist in (ax.title, ax.xaxis.label, ax.yaxis.label, ax.get_legend()):
                    if artist is not None:
                        box = artist.get_window_extent(renderer)
                        self.assertGreaterEqual(box.x0, 0)
                        self.assertGreaterEqual(box.y0, 0)
                        self.assertLessEqual(box.x1, fig.bbox.x1)
                        self.assertLessEqual(box.y1, fig.bbox.y1)
        for row, maximum in ((0, 50_000), (1, 200), (3, 500)):
            limits = [time.axes[row * 4 + col].get_ylim() for col in range(4)]
            self.assertTrue(all(limit == limits[0] for limit in limits))
            self.assertGreater(limits[0][1], maximum)
        self.assertGreater(scatter.axes[0].get_xlim()[1], 50_000)
        self.assertGreater(scatter.axes[4].get_xlim()[1], 200)
        self.assertTrue(all(ax.get_ylim()[1] > 500 for ax in scatter.axes))

    def test_incomplete_reanalysis_removes_stale_comparison_outputs(self):
        runs = fixture()
        manifest = manifest_for(runs)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            stale = [out / "reports/destination-algorithm-statistics.csv",
                     out / "plots/algorithm-metrics-over-time.pdf",
                     out / "plots/algorithm-metrics-vs-goodput.pdf"]
            for path in stale:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("stale output")
            with patch("comparison_plots.plot_comparison") as plot:
                build_report(manifest, runs[:-1], out)
            plot.assert_not_called()
            self.assertTrue(all(not path.exists() for path in stale))
            with (out / "reports/per-test-statistics.csv").open() as stream:
                self.assertTrue(all(row["matched_destination"] == "False" for row in csv.DictReader(stream)))
            report = (out / "reports/algorithm-comparison-report.md").read_text()
            self.assertIn("Completed matched destinations: 0/1", report)
            self.assertIn("Excluded incomplete or mismatched", report)
            self.assertNotIn("highest measured mean goodput", report)


if __name__ == "__main__":
    unittest.main()
