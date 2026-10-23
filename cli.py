import argparse
from math import isfinite
from pathlib import Path


def to_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None


def to_float(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a float") from None


def port_type(value: str) -> int:
    port = to_int(value)

    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535 (inclusive)")

    return port


def check_positive[T: (int, float)](num: T) -> T:
    if isinstance(num, float) and not isfinite(num):
        raise argparse.ArgumentTypeError("must be finite")
    if num <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return num


def positive_int_type(value: str) -> int:
    return check_positive(to_int(value))


def positive_float_type(value: str) -> float:
    return check_positive(to_float(value))


def add_client_args(parser: argparse.ArgumentParser) -> None:
    client = parser.add_argument_group("client")
    client.add_argument(
        "--algorithm", default=None, help="Data socket congestion control algorithm"
    )
    client.add_argument(
        "-t", "--time", type=positive_int_type, default=10, metavar="SECONDS", help="Test duration"
    )
    client.add_argument(
        "-i",
        "--print-interval",
        type=positive_float_type,
        default=5.0,
        metavar="SECONDS",
        help="How often test progress is printed",
    )
    client.add_argument(
        "-g",
        "--goodput-interval",
        type=positive_float_type,
        default=0.2,
        metavar="SECONDS",
        help="How often goodput is measured during test",
    )
    client.add_argument(
        "--connect-timeout",
        type=positive_float_type,
        default=5.0,
        metavar="SECONDS",
        help="Timeout for establishing connection with server",
    )
    client.add_argument(
        "--control-timeout",
        type=positive_float_type,
        default=3.0,
        metavar="SECONDS",
        help="Timeout for communicating over control socket",
    )
    client.add_argument(
        "--data-timeout",
        type=positive_float_type,
        default=3.0,
        metavar="SECONDS",
        help="Timeout for communicating over data socket",
    )

    output = parser.add_argument_group("output")
    output.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "results",
        metavar="DIR",
        help="Directory for raw measurements and plots",
    )
    output.add_argument(
        "--run-id",
        default=None,
        metavar="ID",
        help="Run identifier recorded in the output (default: UTC timestamp)",
    )


def add_analyze_command(commands):
    analyze = commands.add_parser("analyze", help="Rebuild comparison plots and report offline")
    analyze.add_argument("--manifest", type=Path, required=True)


def add_compare_command(commands):
    compare = commands.add_parser("compare", help="Repeat matched congestion control experiments")
    compare.add_argument("-s", "--servers", type=Path, required=True)
    compare.add_argument("-c", "--count", type=positive_int_type, default=3)
    compare.add_argument(
        "-a",
        "--attempts",
        type=positive_int_type,
        default=3,
        help="Maximum candidate destinations per requested destination",
    )
    compare.add_argument("-r", "--repetitions", type=positive_int_type, default=3)
    compare.add_argument("--algorithms", nargs="+", default=["cubic", "reno", "bbr", "a3_cc"])
    compare.add_argument("--seed", type=int, default=422)
    compare.add_argument(
        "--pause", type=positive_float_type, default=2, help="Seconds between tests"
    )
    add_client_args(compare)


def add_test_command(commands):
    test = commands.add_parser(
        "test",
        help="Run a TCP upload test against an iPerf3 server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    server = test.add_argument_group("server")
    server.add_argument("-s", "--host", required=True, help="Server hostname or IP address")
    server.add_argument("-p", "--port", type=port_type, default=5201, help="Server TCP port")

    add_client_args(test)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI for CS422 Assignment 3")
    commands = parser.add_subparsers(dest="command", required=True)

    add_test_command(commands)
    add_compare_command(commands)
    add_analyze_command(commands)

    return parser
