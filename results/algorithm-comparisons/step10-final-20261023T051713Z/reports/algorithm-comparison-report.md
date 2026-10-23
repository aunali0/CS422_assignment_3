# Assignment 3: congestion control comparison

Completed matched destinations: 3/3. Algorithms: cubic, reno, bbr, a3_cc. Repetitions per algorithm: 3. Duration: 10 s. Sampling: 0.2 s. Seed: 422. Host kernel: 6.18.33.2-microsoft-standard-WSL2.

Test order: seeded initial shuffle; rotate by repetition and candidate index. Exact order, settings, and failures are saved in manifest.json and experiment.log. Only complete groups with matching settings enter comparisons. Successful partial runs remain in per-test-statistics.csv.

Per-run goodput uses acknowledged-byte differences divided by actual elapsed time. Throughput and RTT aggregates are the mean and sample standard deviation across runs. Per-run RTT is the mean sampled smoothed RTT. Retransmitted segments are a loss proxy, not an exact packet-loss probability.

dal.speedtest.clouvider.net:5200 | reno | 3 runs: goodput 253.395 ± 7.888 Mbit/s; RTT 79.114 ± 2.312 ms.

dal.speedtest.clouvider.net:5200 | cubic | 3 runs: goodput 133.716 ± 119.746 Mbit/s; RTT 47.540 ± 22.264 ms.

dal.speedtest.clouvider.net:5200 | bbr | 3 runs: goodput 260.518 ± 5.677 Mbit/s; RTT 75.082 ± 1.320 ms.

dal.speedtest.clouvider.net:5200 | a3_cc | 3 runs: goodput 60.438 ± 28.944 Mbit/s; RTT 34.010 ± 1.093 ms.

185.152.66.67:5201 | cubic | 3 runs: goodput 259.124 ± 8.588 Mbit/s; RTT 62.337 ± 12.217 ms.

185.152.66.67:5201 | bbr | 3 runs: goodput 249.258 ± 8.464 Mbit/s; RTT 75.228 ± 5.726 ms.

185.152.66.67:5201 | a3_cc | 3 runs: goodput 9.690 ± 13.706 Mbit/s; RTT 33.395 ± 3.030 ms.

185.152.66.67:5201 | reno | 3 runs: goodput 211.402 ± 51.549 Mbit/s; RTT 50.627 ± 22.516 ms.

96.45.41.167:30001 | a3_cc | 3 runs: goodput 117.212 ± 61.154 Mbit/s; RTT 121.351 ± 4.099 ms.

96.45.41.167:30001 | reno | 3 runs: goodput 161.616 ± 6.207 Mbit/s; RTT 123.553 ± 2.781 ms.

96.45.41.167:30001 | cubic | 3 runs: goodput 164.398 ± 4.176 Mbit/s; RTT 121.703 ± 3.684 ms.

96.45.41.167:30001 | bbr | 3 runs: goodput 156.326 ± 18.618 Mbit/s; RTT 125.369 ± 13.224 ms.

Limitations: sequential public-server tests cannot hold routes, cross-traffic, or server limits constant. Small differences relative to run variability do not establish an advantage. These single-flow tests do not establish fairness or convergence.

AI assistance: an AI coding assistant helped implement the controller, experiment automation, tests, plots, and draft explanatory text. The team must review and explain the implementation and observed differences in the final report.
