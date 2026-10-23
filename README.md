# Assignment 3 controller

This directory is self-contained and can be copied into its own repository. It
includes the eBPF controller, Python iperf3 client, comparison runner, plotting
code, offline tests, server-list snapshot, design documents, dependency files,
and saved smoke-test results. Python imports and report inputs stay within this
directory; no Assignment 2 modules or results are required.

The Python files were copied from Assignment 2 so future changes here are
independent. The selected design is preserved verbatim. Its statement that it
was unimplemented describes the original proposal; the implementation and
verification status below are current. See the verification sections below for
completed work and remaining steps.

`a3_cc` implements the selected normal window rules from
[Q3_DESIGN.md](Q3_DESIGN.md). Step 3 added registration, step 4 added measurement
accounting, step 5 added startup and normal window decisions, and step 6 connects
recovery, timeout/loss-state, undo, and restart notifications. The
[measurement accounting](#measurement-accounting), [normal window rules](#normal-window-rules),
and [recovery, timeouts, and restarts](#recovery-timeouts-and-restarts) sections
explain the callback behavior. Step 7 verifies the complete controller locally
without contacting servers.

## Build and check

Run these commands from this directory (`cd assignment3` while it is nested in Assignment 2):

```sh
uv sync --locked
make all test
sudo ./verify.sh
```

`uv sync --locked` creates this directory's own `.venv` using its dependency
manifest and lockfile. The copied Python client requires Python 3.12 or newer.
The eBPF build still requires the Linux tools and privileges described below.

To inspect the Python commands without contacting servers:

```sh
.venv/bin/python main.py --help
.venv/bin/python main.py compare --help
.venv/bin/python -m unittest discover -s . -p 'test_*.py' -v
```

Measurement commands must still be authorized separately. Defaults match the
planned Assignment 3 comparison: ten-second tests, 0.2-second sampling, three
destinations, three repetitions, and `cubic`, `reno`, `bbr`, `a3_cc`. Default
output always goes to this directory's `results`, including when `main.py` is
launched from another working directory.
Use the included `iperf3-servers.csv` when a server list is required. An existing
comparison manifest can be analyzed offline with `main.py analyze --manifest PATH`.

`make test` runs deterministic accounting, window, and recovery checks without
privileges or network access. `verify.sh` checks that the binaries are current,
runs those tests, and performs four registration/removal cycles. Two use the
loader's `--check` mode; the other two keep it running briefly before sending
SIGINT and SIGTERM. Each cycle selects `a3_cc` on an **unconnected** TCP socket,
reads the algorithm back, closes the socket, unloads the controller, and checks
that it is no longer selectable. The script also checks that the system's default
algorithm stays unchanged. Any failure returns a nonzero status.

The script uses standard Linux shell tools, including `timeout` from coreutils.
It refuses to run if another loader already has `a3_cc` registered. It does not
connect, listen, or send data. For a single registration/removal check, use
`sudo ./loader --check`.

To keep the controller registered until Ctrl+C:

```sh
sudo ./loader
```

SIGINT and SIGTERM both trigger cleanup. Nothing is pinned in bpffs. The system's
default congestion algorithm is unchanged; the controller is available for
selection on individual sockets, including sockets opened by an ordinary user.
Close any sockets using it before checking that unloading has completed.

Load/registration errors are printed by libbpf and the loader on standard error;
verifier failures include libbpf's diagnostic output. While the loader is running,
registration and program details can also be inspected in another terminal:

```sh
sudo bpftool struct_ops show
sudo bpftool prog show
```

## Files and requirements

- `controller.bpf.c`: kernel callbacks, per-socket initialization, RTT/ACK
  collection, normal window updates, and the `a3_cc` registration.
- `accounting.h`: shared interval and goodput calculations used by eBPF and tests.
- `test_accounting.c`: deterministic inputs and expected accounting results.
- `window.h`: the per-connection startup flag and testable normal window rules.
- `test_window.c`: window-rule checks, including accounting and decisions together.
- `recovery.h`: recovery mode changes, history resets, and threshold/undo formulas.
- `test_recovery.c`: recovery sequences, repeated notifications, and restart checks.
- `loader.c`: registration, socket checks, and cleanup.
- `verify.sh`: repeated registration/readback/removal, signal cleanup, and default
  algorithm checks; runs the already-built deterministic tests too.
- `Makefile`: generates the kernel header and libbpf skeleton, then builds both
  the eBPF object and loader. Generated files are ignored by Git.
- `main.py`, `cli.py`: Python commands and argument parsing.
- `client.py`, `protocol.py`, `tcp_info.py`, `log_utils.py`: the socket client,
  iperf3 exchange, TCP statistics, and logging.
- `measurement.py`: acknowledged-throughput samples, metadata, and CSV/JSON persistence.
- `comparison.py`, `comparison_plots.py`: matched experiments,
  offline analysis, statistics, and PDF plots.
- `test_comparison.py`, `test_reporting.py`: three socket-selection checks
  and six four-algorithm reporting checks. Synthetic fixtures and generated
  reports stay in temporary directories.
- `test_standalone.py`: checks that application modules come from this directory,
  that default results stay here when launched from another directory, and
  that the CLI exposes only the retained commands with Assignment 3 defaults.
- `pyproject.toml`, `uv.lock`, `iperf3-servers.csv`: independent Python dependency
  metadata, locked versions, and the server-list snapshot.

Use Linux with BTF and BPF TCP struct-ops support, Clang with the BPF backend,
bpftool, a C compiler, make, pkg-config, and libbpf development files. This setup
targets the kernel and toolchain checked in step 1; loading requires sufficient
host privileges. The Makefile defaults to `clang-21`; override it with
`make CLANG=clang` if appropriate.

After changing kernels, rebuild generated files:

```sh
make clean
make
```

## Measurement accounting

Each socket has its own accounting and startup flag in `icsk_ca_priv`; the build
checks that they fit. Accounting remains unchanged in its own structure; adding
the startup flag alongside it makes the complete state 56 bytes on this target,
within the kernel's 104-byte area. `pkts_acked` records positive RTT samples and
newly acknowledged data segments while established.
The minimum RTT lasts for the connection; missing RTT samples do not replace it.
Handshake/teardown ACKs are excluded. Segment counts come from the kernel, not
the number of ACK messages.

`cong_avoid` checks for a completed eligible interval before making a window decision:

- The first valid reading saves a time/byte baseline without producing a sample.
- The interval uses the smoothed RTT captured at its start. Linux stores this
  RTT scaled by eight, so the callback shifts it right by three.
- A sample needs positive cumulative-byte progress and at least one captured
  RTT of elapsed time. It uses the actual monotonic time in microseconds:
  `goodput = acknowledged_bytes_change * 1_000_000 / elapsed_microseconds`.
- Goodput is integer **bytes/second** internally. The Python client's reporting
  units are unchanged. The returned sample includes the preceding eligible
  rate and its validity flag; state then retains the newly completed rate for
  the next comparison.
- Start the next interval at the current ACK. Multiple ACKs within one RTT are
  accumulated; delayed callbacks produce one sample, without a catch-up loop.
- Limited intervals are skipped using kernel application/receiver limitation
  indicators and the congestion-window-limited flag. Invalid time/counter
  readings and rate overflow clear history. Resets preserve minimum RTT and
  require a fresh baseline when the interval is inactive.

Recovery-state ACKs clear interval history while retaining valid minimum RTT
samples. State changes, restarts, and undo also clear history as described below.

## Normal window rules

Initialization starts in slow start with a window of 10 segments, respecting any
smaller window or clamp already selected by Linux. The initial threshold uses
Linux's unlimited-threshold sentinel.

At each completed eligible interval, compare the current smoothed RTT with the
minimum measured RTT. Window sizes and acknowledged segment counts use segments:

| Condition | Action |
| --- | --- |
| In startup, below `ssthresh`, RTT at most 110% of minimum | Add acknowledged segments, capped at the current window size. |
| Otherwise | Leave startup and apply one of the following three rules. |
| RTT above 125% of minimum, previous goodput exists, current goodput is no better | Set window to `max(2, floor(9 * cwnd / 10))`, then set `ssthresh` to the resulting clamped window. |
| Otherwise, RTT at most 110% of minimum | Add one segment. |
| Otherwise | Hold the window. |

Every result respects `snd_cwnd_clamp`. Comparisons use widened integer
arithmetic, such as `100 * RTT <= 110 * minimum_RTT`, to avoid floating point,
premature rounding, or overflow. A two-segment minimum applies only to the
reduction formula; holding a one-segment window leaves it at one.

The custom rules replace Reno's normal growth callback. Calling Reno as well
would add extra growth outside the once-per-RTT policy. Linux still owns ACK
processing, retransmission, recovery sending, and pacing because `cong_control`
remains unset. Threshold and undo use the same formulas as Reno, implemented in
the shared recovery header so deterministic tests exercise the production logic.

For the oral evaluation, understand that accounting saves the completed rate
for next time but returns the *old* rate in the sample. The decision compares
against that old rate. Also, skipped or incomplete intervals do not change the
window or startup flag. Leaving startup is permanent during normal decisions;
entering Linux's loss state enables startup again.

## Recovery, timeouts, and restarts

| Notification | Controller action | Linux action |
| --- | --- | --- |
| `ssthresh` request | Return `max(2, floor(cwnd / 2))`; change no window or measurement state. | Decide whether a recovery episode needs a new threshold and apply recovery. |
| Enter `Recovery` or ECN `CWR` | Disable startup; clear interval history. | Control recovery sending and retransmissions. |
| Enter `Loss` | Enable startup; clear interval history. | Select the loss/timeout window and recovery behavior. |
| Leave recovery/loss for `Open` or `Disorder` | Clear history; retain the startup mode selected on entry. | Complete or undo recovery. |
| `undo_cwnd` | Clear history; return `max(cwnd, prior_cwnd)`. | Apply the returned window if recovery was spurious. |
| Window restart | Clear history without changing startup mode. | Adjust the window after idle. |
| Transmission start | Clear history only when current or remembered limitation indicators show a pause/limited interval. | Resume sending. |

For the oral evaluation, the threshold request and state notification are
different jobs. Linux can ask for a threshold before calling `set_state`.
`set_state` must use its `new_state` argument because the socket still contains
the old state until the callback returns. It never writes `cwnd` or `ssthresh`.
Repeated notifications therefore repeat only harmless history resets, without
applying another reduction. Linux already decides when a new episode needs
another threshold; we do not add an independent episode counter or loss detector.
`CA_EVENT_LOSS` needs no second response in `cwnd_event`; `set_state` handles the mode.

`TCP_CA_Loss` includes timeout recovery and cases such as SACK reneging. It does
not prove that a timer expired. We leave its actual window to Linux, including
when that window is one segment. The kernel can also initially choose packets
in flight plus one; the controller never forces a fixed timeout window.

Normal decisions are blocked in `CWR`, `Recovery`, and `Loss`. After an exit,
accounting needs a fresh baseline and a full eligible RTT interval before normal
growth or delay-based reduction can resume. Resets preserve the connection's
minimum RTT. An empty flight alone does not prove application idle, so every
`CA_EVENT_TX_START` does not automatically reset the measurements.

## Verification status

The eBPF object and loader compile successfully on
`6.18.33.2-microsoft-standard-WSL2` with Clang 21 and libbpf 1.6.3. GCC's static
analysis and the existing three mocked socket-selection tests passed.

The **step 3 baseline** runtime check passed when run by the user with sudo:

```text
Registered a3_cc (temporary Reno baseline); socket readback passed.
Unloaded a3_cc; algorithm removal check passed.
```

The eight accounting test groups cover units and previous rates, invalid RTT,
zero ACK progress, RTT boundaries/ACK aggregation, resets, invalid
time/counters/overflow, limited intervals, and independent connections.

Step 5 adds eight window test groups: initialization, startup versus congestion
avoidance, delay threshold boundaries, the goodput condition, window limits and
wide arithmetic, once-per-RTT decisions, application/receiver-limited intervals
(which share the same skip flag), and comparison with the correct previous
sample. The window tests also passed with UndefinedBehaviorSanitizer enabled.
The updated BPF object and loader compile with warnings treated as errors;
loader static analysis and the three existing mocked socket-selection tests pass.

Step 6 adds seven recovery test groups covering the half-window threshold and
repeated loss notifications, state transitions, timeout-window preservation and
resumption, all three recovery guards, undo, restarts, and independent connections.
All 23 groups pass. The recovery sequence tests use explicit stand-ins for
Linux's window changes; they test our callbacks' shared logic, not Linux's PRR
implementation or real packet loss. The recovery tests also pass with
UndefinedBehaviorSanitizer and GCC static analysis. BTF-based compile checks
confirm the new callback signatures and the unchanged 56-byte private state;
the three existing mocked socket-selection tests still pass.

Step 7 passed with the complete custom policy. A fresh build regenerated the
kernel header and skeleton and rebuilt the loader and all tests. All 23 test
groups passed normally and with UndefinedBehaviorSanitizer enabled. Loader static
analysis and the three existing mocked socket-selection tests also passed.

Noninteractive sudo required authentication in the agent environment. The user
then ran `sudo ./verify.sh` in a terminal and reported successful
repeated registration/readback/removal, SIGINT cleanup, SIGTERM cleanup, and an
unchanged default algorithm. Its final output was:

```text
Local verification passed; the default algorithm is unchanged. No servers contacted.
```

This confirms kernel verifier acceptance and registration of the complete policy,
alongside the deterministic checks of steps 4–6. Initialization rules are tested
in the shared C code. An unconnected socket does not execute the real connection
initialization or ACK/recovery sequence: those callback timings and behavior under
actual packet loss, timeouts, and receiver/application limits remain unverified.
No network measurements were collected. Step 7 stops here; step 8 requires
explicit authorization to collect traffic measurements.

## Step 8 smoke test

After explicit authorization, one ten-second upload to
`dal.speedtest.clouvider.net:5200` completed using `a3_cc` with 0.2-second sampling.
The existing Python client completed the iperf3 exchange and saved 50 samples.
The controller and selected algorithm were unchanged; no replacement or repeat
transfer was performed.

The [smoke-test report](results/single-server-tests/step8-smoke-20261023T042549Z/smoke-check.md)
links the exact command, client log, raw CSV, metadata/units, and both PDF plots.
Duration-weighted acknowledged throughput was 127.651 Mbit/s; mean sampled RTT
was 33.935 ms. The recorded byte/counter differences and goodput calculations
agree, allowing for CSV rounding. Submitted-versus-acknowledged byte differences
also agree with the queued and in-flight data at the final reading.

The saved command and log predate the standalone copy and record execution from
the Assignment 2 repository root. They are historical records; current commands
run from this directory using its own client and `results` folder.

The window reached 723 segments and ended at 224; goodput ended near 78 Mbit/s.
These reductions are consistent with the selected delay/goodput policy and are
a performance concern for later matched comparisons. This single run does not
establish comparative performance, fairness, or the exact trigger of every cut.
No retransmissions or timeouts were recorded, so live recovery behavior remains
unverified.

Inspecting the generated plot exposed a shared plotting bug: `plots.py` did not
exclude Linux's unlimited-ssthresh sentinel, 2**31-1. Its filter was corrected and
the smoke-test PDFs regenerated offline from unchanged raw samples. All 23 C
test groups and all nine existing Python tests passed; the corrected plot's
window axis was checked to cover the actual window values rather than billions.
Step 8 passed and stops here. Further measurements require new authorization.

## Step 9: offline four-algorithm reporting

The comparison runner supports `cubic`, `reno`, `bbr`, and `a3_cc`.
The CLI now selects all four by default for comparisons.

The local reporting code includes the step 9 changes:

- `comparison_plots.py` uses Assignment 3 titles, one column and color per
  algorithm, repetition-specific line styles and markers, and common scales
  for each metric in the time-series and scatter figures.
- Before aggregating, `matched_destinations` requires exactly one successful run
  for every algorithm/repetition pair. Metadata must agree with the requested
  and recorded algorithm, destination, duration, and sampling interval. Duplicate,
  incomplete, or mismatched groups are excluded from matched summaries and
  comparison plots. Their successful partial runs remain in per-test statistics.
  Reports list groups rejected by this extra check; the manifest is not rewritten.
- Reanalysis removes obsolete aggregate CSVs and representative plots if no
  complete group remains. If the original representative is excluded, the first
  remaining complete destination is used, without selecting for performance.
- Assignment 2's `reviewed_report.py` and historical narrative are not imported
  or copied. Analysis always uses the general Markdown/PDF report generated
  from the local manifest and measurements.
- `test_comparison.py` retains checks that the requested algorithm is selected
  before connecting, a readback mismatch prevents connection, and unavailable
  algorithms fail preflight without substitution.

`test_reporting.py` adds six offline tests. Synthetic samples are clearly labeled
as fixtures and all outputs go into temporary directories. Socket creation and
DNS resolution are blocked unless replaced with mocks. The checks cover:

- Four-name preflight and unconnected algorithm readback, using mocks.
- Missing/duplicate runs, mismatched settings/algorithms/destinations, and failed
  statuses; a valid destination survives alongside an incomplete one.
- A mocked four-algorithm run with three repetitions, two failures, and a whole
  replacement destination. Failed statuses/reasons, the log, and successful
  partial raw files remain available. Saved CSVs feed the real report builder.
- All four aggregate rows, weighted-throughput and mean-RTT arithmetic,
  PDF creation, all repetition labels, consistent colors, and common scales.
- A fourth algorithm with the largest values, verifying common scales include
  those extremes and rendered titles, labels, and legends fit the figure.
- Removal of stale comparison outputs after an incomplete reanalysis, and
  absence of Assignment 2's reviewed report from four-algorithm output.

Run these checks from this directory after setting up its Python environment:

```sh
MPLCONFIGDIR=/tmp/a3-matplotlib .venv/bin/python -m unittest discover -s . -p test_reporting.py -v
MPLCONFIGDIR=/tmp/a3-matplotlib .venv/bin/python -m unittest discover -s . -p test_comparison.py -v
make all test
```

All six reporting tests, three socket-selection tests, and 23 C test groups pass. Offline
PDF previews were also inspected. No controller code, selected algorithm, or
saved experiment results changed, and no network measurements were collected.
Real four-algorithm performance and availability on a future measurement host
remain unverified. The step 8 smoke test and older Assignment 2 measurements have
different settings and must not be combined into a matched comparison.

Step 9 stops here. Step 10 requires explicit authorization for new measurements.

## Standalone copy verification

The complete Python suite now has 12 tests: three socket-selection tests,
six reporting tests, and three independence/CLI checks. The suite and all 23 C check
groups pass. The local lockfile also passes `uv lock --check --offline`.

Independence was checked by copying this directory into a temporary location
without Assignment 2's source tree, checking the CLI, and running the Python
tests there with the installed dependency environment. No new dependency
installation or network measurements were needed. The selected controller and
saved experiment files were preserved.

## Assignment 3 scope

Option 1 requires the implemented controller; ten-second transfers logging the
actual algorithm, cwnd, acknowledged throughput, RTT, and a loss proxy; repeated
matched tests of all four algorithms; time-series and scatter plots for one
common representative destination; and aggregate throughput/RTT statistics.
The existing C tests and focused Python tests check that implementation.

The retained commands are `test` (record one transfer), `compare` (run matched
experiments), and `analyze` (rebuild the comparison offline). New runs save raw
CSV/JSON records. Comparison reports include per-run goodput, RTT, and retransmit
counts; per-destination/algorithm throughput and RTT means and sample standard
deviations; settings and test order; and the two required comparison figures.

Removed Assignment 2-only code includes the separate `destinations` workflow,
its destination plots and summary PDF, per-run PDF generation, min/median/P95 and
BDP summaries, unused logging suppression, and duplicate legacy tests. Old smoke
test files remain unchanged as evidence of completed work. The controller,
selected algorithm, and design are unchanged; final measurements and the written
analysis remain steps 10 and 11 and have not been performed by this cleanup.

## Step 10: final comparison completed

After explicit authorization, the existing runner completed the final comparison
in about 18 minutes. It retained three complete destinations and 36 tests. Eight
candidates required 96 attempts: 75 succeeded and 21 failed. The 39 successful
tests from incomplete groups remain saved and are excluded from matched averages.
No controller or client implementation changed. Twelve Python checks and all
23 C check groups passed before collection.

The [verification notes](results/algorithm-comparisons/step10-final-20261023T051713Z/verification-notes.md)
link the raw data, manifest, statistics, plots, exact invocation, source/build
checksums, and verification results. All 3,750 samples from the 75 successful
runs passed counter, timing, and goodput checks. Raw-data calculations also agree
with every per-run summary and all 12 destination/algorithm aggregates.

For reproduction, keep `sudo ./loader` running in another terminal while
collecting. Registration requires appropriate privileges but does not contact
servers. Each requested algorithm must be available before transfers begin.

After explicit measurement authorization, run from this directory using the
Python environment set up above:

```sh
.venv/bin/python main.py compare -s iperf3-servers.csv \
  --algorithms cubic reno bbr a3_cc -t 10 -g 0.2 \
  -c 3 -r 3 -a 3 --seed 422 --pause 2
```

This requests 36 retained tests: three destinations, four algorithms, and three
repetitions. The runner tries at most nine candidate destinations, allowing at
most 108 transfers before reporting a shortfall. It stops once three complete
groups succeed. Each transfer lasts ten seconds; sampling and all other client
settings are shared. The algorithm is selected on each data socket and read back;
there is no fallback if a requested algorithm is unavailable.

The runner shuffles and rotates test order, records the exact sequence and
failures in `manifest.json`, and saves raw samples, metadata, logs, aggregate
statistics, and the two required comparison figures under
`results/algorithm-comparisons/<UTC run id>/`. Three repetitions do not fully
balance all four order positions; rotating reduces order bias without removing
it. A destination is retained only when all twelve tests succeed.

The retained destinations are `dal.speedtest.clouvider.net:5200`,
`185.152.66.67:5201`, and `96.45.41.167:30001`. All algorithm readbacks, settings,
complete-group checks, and exported summaries passed validation; both required
figures were visually checked. The custom algorithm had lower mean goodput than
each baseline at all three destinations. These single-flow measurements do not
establish fairness or convergence. Step 10 stops here; the final written report
and explanation of observed differences belong to step 11.
