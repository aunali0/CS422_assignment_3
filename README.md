# CS 422 Assignment 3: TCP Congestion Control

This project implements `a3_cc`, a custom Linux TCP congestion controller using
eBPF, and compares it with CUBIC, Reno, and BBR on public iperf3 servers. It follows
Option 1 and builds on the socket client and [algorithm design](Q3_DESIGN.md) from
Assignment 2. This repository is self-contained; Assignment 2 is not required.

## Implementation

The Python client performs the iperf3 exchange, selects and verifies the algorithm
on each data socket, and sends data for a configurable duration. Linux runs the
controller as ACKs arrive; Python records measurements.

- `controller.bpf.c` supplies TCP callbacks; `accounting.h`, `window.h`, and
  `recovery.h` contain the controller rules.
- `loader.c` registers and unloads `a3_cc` without changing the system default.
- `client.py`, `protocol.py`, and `tcp_info.py` handle transfers and `TCP_INFO`.
- `measurement.py`, `comparison.py`, and `comparison_plots.py` save data, run
  comparisons, and produce statistics and plots.

## Controller policy

Each connection tracks minimum RTT and acknowledged bytes. At most once per
eligible RTT, the controller computes goodput using byte progress and actual
elapsed time. Intervals without ACK progress or limited by the application,
receive window, or send buffer do not drive normal window decisions.

The initial window is at most ten segments. Startup grows by the newly
acknowledged segment count, capped at one current window per interval, while RTT
is within 10% of the minimum and the window is below the slow-start threshold.
After startup:

| Condition | Window change |
| --- | --- |
| RTT at most 1.10 times minimum RTT | Increase by one segment |
| RTT above 1.25 times minimum RTT and goodput has not increased | Reduce by 10%, with a minimum of two segments |
| Otherwise | Hold |

All changes respect Linux's window limit. Loss uses a Reno-style half-window
threshold; Linux retains responsibility for retransmissions and recovery.
Recovery resets stale measurement history. The aim is to limit queue buildup.

## Experiment and findings

The comparison used ten-second uploads, 0.2-second logging, and three repetitions
per algorithm at three destinations. Logging is separate from the controller's
RTT-based decisions. Goodput uses acknowledged-byte progress divided by actual
elapsed time, converted to Mbit/s; retransmissions are a loss proxy.

Tests used a seeded, rotated order and bounded replacement attempts. Across eight
candidates, 75 tests succeeded and 21 failed. Only the 36 tests from complete
destination groups enter the matched comparison; partial results remain saved.

Mean goodput across three runs, in Mbit/s:

| Destination | CUBIC | Reno | BBR | `a3_cc` |
| --- | ---: | ---: | ---: | ---: |
| dal.speedtest.clouvider.net:5200 | 133.72 | 253.39 | 260.52 | 60.44 |
| 185.152.66.67:5201 | 259.12 | 211.40 | 249.26 | 9.69 |
| 96.45.41.167:30001 | 164.40 | 161.62 | 156.33 | 117.21 |

`a3_cc` had the lowest mean goodput and lowest mean RTT at all three destinations.
Throughput was sometimes substantially lower; these results do not demonstrate
an overall improvement. Public-server variability limits causal explanations,
short tests include startup, and the experiment does not establish fairness or
convergence.

The saved results include [throughput and RTT statistics with sample standard deviations](results/algorithm-comparisons/step10-final-20261023T051713Z/reports/destination-algorithm-statistics.csv),
[time-series plots](results/algorithm-comparisons/step10-final-20261023T051713Z/plots/algorithm-metrics-over-time.pdf),
and [scatter plots](results/algorithm-comparisons/step10-final-20261023T051713Z/plots/algorithm-metrics-vs-goodput.pdf).
Both figures use Dallas as the common representative destination.
[Verification notes](results/algorithm-comparisons/step10-final-20261023T051713Z/verification-notes.md)
link the raw data, exact command, test order, failures, and toolchain records.

## Validation and requirements

The controller was built and loaded on Linux 6.18.33.2 under WSL2. Requirements
include kernel BTF and eBPF TCP struct-ops support, BPF-capable Clang (`clang-21`
by default), bpftool, libbpf development files, and Python 3.12+.

All 23 C test groups and 12 Python tests passed. Local verification covered
registration, socket readback, removal, and signal cleanup. Saved measurements
passed counter, timing, and statistics checks. Every possible kernel recovery
sequence remains unverified.

`uv sync --locked` installs Python dependencies; `make all test` builds the
controller and runs C checks. `sudo ./verify.sh` checks loading without server
traffic, while `sudo ./loader` keeps the controller registered. Python exposes
`test`, `compare`, and offline `analyze` commands through `main.py`, with outputs
under `results/` and no silent algorithm substitution.

AI assistance was used for implementation, tests, automation, plots, and draft
text. The team remains responsible for understanding and explaining the work.
