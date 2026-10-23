# holds per sample record, run metadata, and csv/json persistence

import csv
import json
import platform
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from log_utils import log_message
from tcp_info import TCP_INFO_FIELDS, TCP_INFO_UNITS, TcpInfo

# Loss proxy: TCP exposes no direct per-interval loss count, so we use the growth of
# tcpi_total_retrans (segments the sender retransmitted) over the sampling interval.
# tcpi_lost is NOT cumulative: it is the kernel's current estimate of segments
# lost in the in-progress recovery, so it is logged but never differenced.

SAMPLE_UNITS: dict[str, str] = {
    "run_id": "id",
    "destination": "host:port",
    "host": "hostname",
    "port": "port",
    "algorithm": "name",
    "time": "s",
    "interval": "s",
    "goodput": "Mbit/s",
    "bytes_acked_delta": "bytes",
    "retrans_delta": "segments",
}

SAMPLE_COLUMNS = tuple(SAMPLE_UNITS)
TCP_INFO_COLUMNS = tuple(f"tcpi_{name}" for name, _ in TCP_INFO_FIELDS)
CSV_COLUMNS = SAMPLE_COLUMNS + TCP_INFO_COLUMNS

CSV_UNITS = {**SAMPLE_UNITS, **{f"tcpi_{name}": unit for name, unit in TCP_INFO_UNITS.items()}}


@dataclass(frozen=True)
class Sample:
    time: float  # seconds since the first byte of the test
    interval: float  # seconds this sample covers
    goodput: float  # Mbit/s = (delta bytes acknowledged / delta t) * 8 / 1e6
    bytes_acked_delta: int
    retrans_delta: int | None
    info: TcpInfo

    def rtt_ms(self) -> float | None:
        rtt = self.info["rtt"]
        return None if rtt is None else rtt / 1000


@dataclass(frozen=True)
class RunMetadata:
    run_id: str
    host: str
    port: int
    algorithm: str
    duration: int
    goodput_interval: float
    started_at: str
    kernel: str
    tcp_info_bytes: int  # bytes the kernel actually wrote for struct tcp_info

    def destination(self) -> str:
        return f"{self.host}:{self.port}"

    def slug(self) -> str:
        return re.sub(r"[^A-Za-z0-9._-]", "_", f"{self.run_id}_{self.host}_{self.port}")


def current_metadata(
    run_id: str, host: str, port: int, algorithm: str, duration: int, interval: float, info_len: int
) -> RunMetadata:
    return RunMetadata(
        run_id=run_id,
        host=host,
        port=port,
        algorithm=algorithm,
        duration=duration,
        goodput_interval=interval,
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        kernel=platform.release(),
        tcp_info_bytes=info_len,
    )


def sample_row(meta: RunMetadata, sample: Sample) -> dict[str, object]:
    row: dict[str, object] = {
        "run_id": meta.run_id,
        "destination": meta.destination(),
        "host": meta.host,
        "port": meta.port,
        "algorithm": meta.algorithm,
        "time": round(sample.time, 6),
        "interval": round(sample.interval, 6),
        "goodput": round(sample.goodput, 6),
        "bytes_acked_delta": sample.bytes_acked_delta,
        "retrans_delta": sample.retrans_delta,
    }

    for name, _ in TCP_INFO_FIELDS:
        row[f"tcpi_{name}"] = sample.info[name]

    return row


def create_run_directory(out_dir: Path, run_id: str, category: str) -> Path:
    path = out_dir / category / run_id
    try:
        path.mkdir(parents=True)
    except FileExistsError:
        raise SystemExit(f"Output directory already exists: {path}. Choose a fresh --run-id.") from None
    return path


def save_run(meta: RunMetadata, samples: list[Sample], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "tcp-samples.csv"
    json_path = out_dir / "test-metadata.json"

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        for sample in samples:
            writer.writerow(sample_row(meta, sample))

    metadata = {
        "run_id": meta.run_id,
        "destination": meta.destination(),
        "host": meta.host,
        "port": meta.port,
        "algorithm": meta.algorithm,
        "duration_s": meta.duration,
        "goodput_interval_s": meta.goodput_interval,
        "started_at": meta.started_at,
        "host_kernel": meta.kernel,
        "tcp_info_bytes": meta.tcp_info_bytes,
        "samples": len(samples),
        "units": CSV_UNITS,
    }

    with open(json_path, "w") as f:
        json.dump(metadata, f, indent=2)

    log_message("test", f"Measurements saved to {csv_path}")

    return csv_path
