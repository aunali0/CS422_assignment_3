import csv
import importlib.metadata
import json
import logging
import platform
import random
import socket
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from client import ClientConfig, try_run_test
from measurement import RunMetadata, Sample, create_run_directory, save_run
from tcp_info import TCP_INFO_FIELDS, get_tcp_algorithm, get_tcp_info


@dataclass
class Server:
    host: str
    port: int

    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"


def load_servers(filepath: Path) -> list[Server]:
    with filepath.open() as stream:
        return [Server(row["IP/HOST"], int(row["PORT"].split("-")[0]))
                for row in csv.DictReader(stream)]


def preflight(algorithms: list[str]) -> dict:
    if platform.system() != "Linux":
        raise SystemExit("Run experiments on Linux or WSL2. Offline analysis works on macOS.")
    if len(algorithms) != len(set(algorithms)) or not algorithms:
        raise SystemExit("Algorithm names must be unique and nonempty")
    available = {}
    for algorithm in algorithms:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_CONGESTION, algorithm.encode("ascii")
                )
                actual = get_tcp_algorithm(sock)
                if actual != algorithm:
                    raise OSError(f"kernel selected {actual}")
                info = get_tcp_info(sock)
                required = ("bytes_acked", "snd_cwnd", "rtt", "total_retrans")
                if any(info[name] is None for name in required):
                    raise OSError("kernel TCP_INFO lacks required measurement fields")
                available[algorithm] = actual
        except (OSError, UnicodeError) as error:
            raise SystemExit(
                f"Cannot use {algorithm}: {error}. Ask the Linux host owner to enable it; "
                "BBR may require loading tcp_bbr. No algorithm was substituted."
            ) from error
    return {"kernel": platform.release(), "platform": platform.platform(), "algorithms": available}


def write_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(path)


def load_run(path: Path) -> tuple[RunMetadata, list[Sample]]:
    data = json.loads((path.parent / "test-metadata.json").read_text())
    meta = RunMetadata(
        data["run_id"],
        data["host"],
        data["port"],
        data["algorithm"],
        data["duration_s"],
        data["goodput_interval_s"],
        data["started_at"],
        data["host_kernel"],
        data["tcp_info_bytes"],
    )

    def integer(row, key):
        return int(row[key]) if row.get(key) else None

    with path.open(newline="") as stream:
        samples = [
            Sample(
                time=float(row["time"]),
                interval=float(row["interval"]),
                goodput=float(row["goodput"]),
                bytes_acked_delta=int(row["bytes_acked_delta"]),
                retrans_delta=integer(row, "retrans_delta"),
                info={name: integer(row, f"tcpi_{name}") for name, _ in TCP_INFO_FIELDS},
            )
            for row in csv.DictReader(stream)
        ]
    return meta, samples


def analyze_manifest(path: Path) -> None:
    from comparison_plots import build_report

    manifest = json.loads(path.read_text())
    runs = [
        (test, load_run(path.parent / test["csv"]))
        for test in manifest["tests"]
        if test["status"] == "ok"
    ]
    build_report(manifest, runs, path.parent)


def run_comparison(args, cfg: ClientConfig, run_id: str) -> bool:
    environment = preflight(args.algorithms)
    rng = random.Random(args.seed)
    servers = list({(s.host, s.port): s for s in load_servers(args.servers)}.values())
    rng.shuffle(servers)
    servers = servers[: args.count * args.attempts]
    out = create_run_directory(args.out_dir, run_id, "algorithm-comparisons")
    handler = logging.FileHandler(out / "experiment.log")
    logging.getLogger().addHandler(handler)
    try:
        (out / "servers-input.csv").write_bytes(args.servers.read_bytes())
        environment["python"] = platform.python_version()
        environment["dependencies"] = {
            name: importlib.metadata.version(name) for name in ("matplotlib", "pydantic")
        }

        base_order = list(args.algorithms)
        rng.shuffle(base_order)
        manifest = {
            "run_id": run_id,
            "environment": environment,
            "config": asdict(cfg),
            "algorithms": args.algorithms,
            "repetitions": args.repetitions,
            "seed": args.seed,
            "pause_s": args.pause,
            "requested_destinations": args.count,
            "max_candidates": args.count * args.attempts,
            "candidates": [asdict(s) for s in servers],
            "order_method": "seeded initial shuffle; rotate by repetition and candidate index",
            "selected_destinations": [],
            "representative": None,
            "tests": [],
            "complete": False,
        }
        path = out / "manifest.json"
        write_manifest(path, manifest)
        for index, server in enumerate(servers):
            if len(manifest["selected_destinations"]) >= args.count:
                break
            planned = []
            for repetition in range(args.repetitions):
                shift = (repetition + index) % len(base_order)
                order = base_order[shift:] + base_order[:shift]
                for algorithm in order:
                    planned.append(
                        {
                            "destination": server.endpoint(),
                            "repetition": repetition + 1,
                            "requested_algorithm": algorithm,
                            "status": "pending",
                            "run_id": f"{run_id}-d{index + 1}-r{repetition + 1}-{algorithm}",
                        }
                    )
            manifest["tests"].extend(planned)
            write_manifest(path, manifest)
            for test in planned:
                test["status"] = "running"
                test["started_at_unix_s"] = time.time()
                write_manifest(path, manifest)
                print(
                    f"{test['destination']} | repetition {test['repetition']} | "
                    f"{test['requested_algorithm']}",
                    flush=True,
                )
                result = try_run_test(
                    server.host,
                    server.port,
                    replace(cfg, algorithm=test["requested_algorithm"]),
                    test["run_id"],
                )
                test["finished_at_unix_s"] = time.time()
                if result is None:
                    test.update(status="failed", reason="See experiment.log")
                elif not result.samples:
                    test.update(status="failed", reason="No samples returned")
                elif result.metadata.algorithm != test["requested_algorithm"]:
                    test.update(status="failed", reason="Algorithm readback mismatch")
                else:
                    saved = save_run(
                        result.metadata, result.samples, out / "tcp-traces" / result.metadata.slug()
                    )
                    test.update(
                        status="ok",
                        csv=saved.relative_to(out).as_posix(),
                        actual_algorithm=result.metadata.algorithm,
                    )
                write_manifest(path, manifest)
                time.sleep(args.pause)
            if all(test["status"] == "ok" for test in planned):
                manifest["selected_destinations"].append(server.endpoint())
                if manifest["representative"] is None:
                    manifest["representative"] = server.endpoint()
            write_manifest(path, manifest)
        manifest["complete"] = len(manifest["selected_destinations"]) == args.count
        write_manifest(path, manifest)
        analyze_manifest(path)
        print(
            f"Complete matched destinations: {len(manifest['selected_destinations'])}/{args.count}"
        )
        print(f"Report: {out / 'reports' / 'algorithm-comparison-report.pdf'}")
        return manifest["complete"]
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
