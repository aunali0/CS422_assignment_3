# Step 8 smoke test: passed

One transfer was explicitly authorized and performed. No replacements or repeats
were run. The existing Python client completed the standard iperf3 protocol and
sent IPERF_DONE; its exit status was zero. Controller code and parameters were unchanged.

```sh
.venv/bin/python main.py test -s dal.speedtest.clouvider.net -p 5200 --algorithm a3_cc -t 10 -g 0.2 -i 2 -o assignment3/results --run-id step8-smoke-20261023T042549Z
```

The controller was kept loaded in a separate terminal. Start time:
2026-10-23T04:25:50+00:00; kernel: `6.18.33.2-microsoft-standard-WSL2`.

| Measurement | Result |
| --- | --- |
| Destination | dal.speedtest.clouvider.net:5200 |
| Requested and connected-socket algorithm | a3_cc |
| Nominal duration / final sample time | 10 s / 10.000698 s |
| Sampling interval / sample count | 0.2 s / 50 |
| TCP_INFO bytes returned | 280 |
| Newly acknowledged data | 159,575,392 bytes |
| Duration-weighted acknowledged throughput | 127.651 Mbit/s |
| Sample throughput min / median / max | 12.644 / 130.684 / 214.714 Mbit/s |
| Sample RTT min / mean / max | 31.924 / 33.935 / 41.413 ms |
| Sampled cwnd min / max / final | 161 / 723 / 224 segments |
| Recorded retransmissions / retransmission timeouts | 0 / 0 |

## Data checks

All 50 rows identify a3_cc and contain positive intervals, increasing times,
nonnegative finite goodput, positive RTT, and positive windows. Every consecutive
cumulative-counter difference agrees with its saved delta for acknowledged bytes,
retransmissions, retransmitted bytes, outgoing data segments, and delivered segments.
The first acknowledged-byte delta implies an initial counter of 38 bytes.
The sum of deltas equals the final counter minus that baseline.

Goodput agrees with `delta_bytes * 8 / elapsed_seconds / 1e6` in every row,
allowing for CSV rounding of time and goodput to six decimal places. Sample
intervals sum to the final timestamp within that rounding precision. Weighted
throughput uses total acknowledged bytes divided by total measured time, rather
than an unweighted average of rates.

## Observations and limits

The window reached 723 segments, then underwent several reductions and ended
at 224. Goodput peaked at 214.71 Mbit/s and ended at 77.74 Mbit/s.
Several sampled window cuts match the 90% delay-cut formula, such as 723 to 650
and 650 to 585, with no recorded retransmissions. A final window/RTT estimate,
`cwnd * MSS * 8 / RTT`, is 79.30 Mbit/s, close to the final measured rate.
This is consistent with the smaller window limiting throughput; it is a
performance concern to evaluate in matched comparisons, not a reason to silently
tune the selected algorithm after one run.

CSV samples are 0.2 s apart, while the controller decides approximately once per
RTT. The private lifetime minimum RTT also differs in definition from the TCP_INFO
minimum. These traces cannot reconstruct every decision or prove its exact trigger.
Initial cwnd=10 is covered by deterministic tests; the first recorded live window
is already 161 segments after startup has begun.

The application submitted 162,335,888 bytes. Of these, 2,436,144
were still queued locally at the final reading, leaving 159,899,744 bytes
reported by the receiver. A further 324,352 bytes were in flight
at the final ACK sample, exactly `224 * 1448`.
Submitted, transmitted, and acknowledged bytes therefore need not match at the
same instant; this run's differences agree with the socket counters.

The server's result JSON says congestion_used=cubic. That describes the remote
socket; the uploading sender's actual socket reports a3_cc. iPerf distinguishes
local and remote algorithm reports in its [official implementation](https://github.com/esnet/iperf/blob/3.19/src/iperf_api.c).

All recorded congestion states were Open, with no retransmissions or timeouts.
Live recovery/timeout behavior, fairness, and comparative performance remain
unverified. No further measurements were collected.

## Artifacts

- [Client log](experiment.log) and [exact command](command.txt).
- [Raw samples](tcp-traces/step8-smoke-20261023T042549Z_dal.speedtest.clouvider.net_5200/tcp-samples.csv) and
  [metadata/units](tcp-traces/step8-smoke-20261023T042549Z_dal.speedtest.clouvider.net_5200/test-metadata.json).
- [Time series](tcp-traces/step8-smoke-20261023T042549Z_dal.speedtest.clouvider.net_5200/tcp-metrics-over-time.pdf) and
  [scatter plots](tcp-traces/step8-smoke-20261023T042549Z_dal.speedtest.clouvider.net_5200/tcp-metrics-vs-goodput.pdf).

The unlimited-ssthresh filter in plots.py was corrected after inspecting the first
plot: Linux's sentinel is 2**31-1. The PDFs were regenerated offline from the same
raw measurements so that this sentinel does not flatten the cwnd axis. No
additional transfer was needed.
