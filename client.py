import resource
import secrets
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from json import JSONDecodeError

from pydantic import ValidationError

from log_utils import log_message
from measurement import RunMetadata, Sample, current_metadata
from protocol import (
    IPerf3Test,
    State,
    generate_cookie,
    receive_json,
    receive_state,
    send_json,
    send_state,
)
from tcp_info import (
    field_delta,
    get_tcp_algorithm,
    get_tcp_info,
    get_tcp_info_bytes,
    parse_tcp_info,
)

BUF_SIZE = 128 * 1024


@dataclass(frozen=True)
class ClientConfig:
    duration: int
    print_interval: float
    goodput_interval: float
    connect_timeout: float
    control_timeout: float
    data_timeout: float
    algorithm: str | None = None


@dataclass(frozen=True)
class TestResult:
    metadata: RunMetadata
    samples: list[Sample]
    total_bytes_sent: int


@contextmanager
def data_connection(host: str, port: int, cfg: ClientConfig) -> Iterator[socket.socket]:
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    last_error = None
    for family, kind, proto, _, address in addresses:
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(cfg.connect_timeout)
            if cfg.algorithm:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_CONGESTION, cfg.algorithm.encode())
                actual = get_tcp_algorithm(sock)
                if actual != cfg.algorithm:
                    raise OSError(f"Requested {cfg.algorithm}, got {actual}")
            sock.connect(address)
        except OSError as error:
            sock.close()
            last_error = error
            continue
        with sock:
            yield sock
        return
    raise last_error or OSError(f"No addresses for {host}")


def run_test(host: str, port: int, cfg: ClientConfig, run_id: str) -> TestResult:
    cookie = generate_cookie()

    with socket.create_connection((host, port), timeout=cfg.connect_timeout) as control_sock:
        log_message("control", f"Connected to {host}:{port}")
        control_sock.settimeout(cfg.control_timeout)

        control_sock.sendall(cookie)
        log_message("control", "Sent cookie")

        receive_state(control_sock, State.PARAM_EXCHANGE, "control")

        control_payload: dict[str, object] = {
            "tcp": True,
            "omit": 0,
            "time": cfg.duration,
            "num": 0,
            "blockcount": 0,
            "parallel": 1,
            "len": BUF_SIZE,
        }
        send_json(control_sock, control_payload, "control")

        receive_state(control_sock, State.CREATE_STREAMS, "control")

        with data_connection(host, port, cfg) as data_sock:
            log_message("data", "Connected")
            data_sock.settimeout(cfg.data_timeout)

            data_sock.sendall(cookie)
            log_message("data", "Sent cookie")

            receive_state(control_sock, State.TEST_START, "control")
            receive_state(control_sock, State.TEST_RUNNING, "control")

            log_message("test", f"Uploading for {cfg.duration}s")

            test_payload = secrets.token_bytes(BUF_SIZE)

            algorithm = get_tcp_algorithm(data_sock)
            info_bytes = get_tcp_info_bytes(data_sock)
            metadata = current_metadata(
                run_id, host, port, algorithm, cfg.duration, cfg.goodput_interval, len(info_bytes)
            )
            log_message("test", f"Algorithm {algorithm} | tcp_info {len(info_bytes)} bytes")

            prev_info = parse_tcp_info(info_bytes)
            start_time = time.monotonic()
            end_time = start_time + cfg.duration

            usage_start = resource.getrusage(resource.RUSAGE_SELF)
            total_bytes_sent = 0

            next_print_time = start_time + cfg.print_interval
            next_goodput_time = start_time + cfg.goodput_interval
            data_deadline = start_time + cfg.data_timeout

            prev_sample_time = start_time
            samples: list[Sample] = []

            def take_sample() -> None:
                nonlocal prev_info, prev_sample_time

                info = get_tcp_info(data_sock)
                sample_time = time.monotonic()

                interval = sample_time - prev_sample_time
                bytes_acked_delta = field_delta(info, prev_info, "bytes_acked") or 0

                samples.append(
                    Sample(
                        time=sample_time - start_time,
                        interval=interval,
                        goodput=bytes_acked_delta / interval * 8 / 1e6,
                        bytes_acked_delta=bytes_acked_delta,
                        retrans_delta=field_delta(info, prev_info, "total_retrans"),
                        info=info,
                    )
                )

                prev_info = info
                prev_sample_time = sample_time

            def log_test_progress(time_passed: float) -> None:
                sent = total_bytes_sent / 1024**2
                log_message("test", f"{time_passed:.1f}s / {cfg.duration}s | {sent:.1f} MiB sent")

            while True:
                curr_time = time.monotonic()

                if curr_time >= end_time:
                    break

                if curr_time >= data_deadline:
                    raise TimeoutError("Data socket timed out")

                if curr_time >= next_goodput_time:
                    take_sample()

                    intervals = int((prev_sample_time - start_time) / cfg.goodput_interval) + 1
                    next_goodput_time = start_time + intervals * cfg.goodput_interval

                if curr_time >= next_print_time:
                    log_test_progress(curr_time - start_time)
                    next_print_time = curr_time + cfg.print_interval

                deadline = min(next_goodput_time, next_print_time, end_time, data_deadline)
                data_timeout = deadline - time.monotonic()

                if data_timeout <= 0:
                    continue

                data_sock.settimeout(data_timeout)

                try:
                    bytes_sent = data_sock.send(test_payload)
                except TimeoutError:
                    continue

                if bytes_sent == 0:
                    raise ConnectionError("Data connection closed during test")

                total_bytes_sent += bytes_sent
                data_deadline = time.monotonic() + cfg.data_timeout

            take_sample()

            time_elapsed = time.monotonic() - start_time
            log_test_progress(time_elapsed)

            usage_end = resource.getrusage(resource.RUSAGE_SELF)

            send_state(control_sock, State.TEST_END, "control")
            receive_state(control_sock, State.EXCHANGE_RESULTS, "control")

        user_time = usage_end.ru_utime - usage_start.ru_utime
        sys_time = usage_end.ru_stime - usage_start.ru_stime

        cpu_util_user = user_time / time_elapsed * 100
        cpu_util_sys = sys_time / time_elapsed * 100
        cpu_util_total = cpu_util_user + cpu_util_sys

        test_payload: dict[str, object] = {
            "cpu_util_total": cpu_util_total,
            "cpu_util_user": cpu_util_user,
            "cpu_util_system": cpu_util_sys,
            "sender_has_retransmits": 0,
            "streams": [
                {
                    "id": 1,
                    "bytes": total_bytes_sent,
                    "retransmits": -1,
                    "jitter": 0,
                    "errors": 0,
                    "packets": 0,
                    "start_time": 0,
                    "end_time": time_elapsed,
                }
            ],
        }
        send_json(control_sock, test_payload, "control")
        receive_json(control_sock, IPerf3Test, "control")

        receive_state(control_sock, State.DISPLAY_RESULTS, "control")
        send_state(control_sock, State.IPERF_DONE, "control")

        return TestResult(metadata=metadata, samples=samples, total_bytes_sent=total_bytes_sent)


def try_run_test(
    host: str, port: int, cfg: ClientConfig, run_id: str
) -> TestResult | None:
    try:
        return run_test(host, port, cfg, run_id)

    except (OSError, JSONDecodeError, UnicodeDecodeError, ValidationError) as err:
        log_message("error", f"{host}:{port} | {type(err).__name__}: {err}")
