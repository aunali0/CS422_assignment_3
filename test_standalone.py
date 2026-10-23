import importlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from cli import create_parser


class StandaloneTests(unittest.TestCase):
    def test_application_modules_are_local(self):
        for name in ("main", "cli", "client", "comparison", "comparison_plots",
                     "log_utils", "measurement", "protocol", "tcp_info"):
            with self.subTest(module=name):
                module = importlib.import_module(name)
                self.assertEqual(Path(module.__file__).resolve().parent, ROOT)

    def test_default_output_stays_local_from_another_working_directory(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                for command in (["test", "-s", "offline.invalid"],
                                ["compare", "-s", str(ROOT / "iperf3-servers.csv")]):
                    with self.subTest(command=command[0]):
                        args = create_parser().parse_args(command)
                        self.assertEqual(args.out_dir, ROOT / "results")
            finally:
                os.chdir(previous)

    def test_cli_matches_assignment_three_scope(self):
        args = create_parser().parse_args(["compare", "-s", str(ROOT / "iperf3-servers.csv")])
        self.assertEqual(args.time, 10)
        self.assertEqual(args.goodput_interval, .2)
        self.assertEqual(args.algorithms, ["cubic", "reno", "bbr", "a3_cc"])
        self.assertEqual((args.count, args.repetitions), (3, 3))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            create_parser().parse_args(["destinations", "-s", "offline.csv"])


if __name__ == "__main__":
    unittest.main()
