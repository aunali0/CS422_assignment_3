# Step 10: collection and verification passed

The authorized comparison completed on 2026-10-23T05:37:15+00:00. The attempt sequence took 1062.714 seconds (about 18 minutes). The runner exited successfully and stopped after reaching three complete destinations.

## Collection

- Algorithms: CUBIC, Reno, BBR, and `a3_cc`; three repetitions each.
- Settings: ten-second uploads, 0.2-second sampling, two-second pauses, seed 422.
- Eight candidate destinations tried; 96 attempts, within the nine-candidate/108-attempt limit.
- 75 successful tests and 21 failures: 17 ACCESS_DENIED responses and four timeouts.
- 36 retained tests (1,800 samples); 39 other successful tests belong to incomplete groups.
- All 75 successful tests and their 3,750 samples remain on disk, along with every failure record.
- Dallas was the first complete group and is the representative for both comparison figures.

## Retained mean goodput (Mbit/s)

| Destination | CUBIC | Reno | BBR | a3_cc |
| --- | ---: | ---: | ---: | ---: |
| dal.speedtest.clouvider.net:5200 | 133.716 | 253.395 | 260.518 | 60.438 |
| 185.152.66.67:5201 | 259.124 | 211.402 | 249.258 | 9.690 |
| 96.45.41.167:30001 | 164.398 | 161.616 | 156.326 | 117.212 |

The custom controller had the lowest mean goodput at all three retained destinations. No controller or client code was changed during collection. The final analysis belongs to step 11.

## Verification

- All actual algorithm names agree with both the requests and saved metadata/CSV rows.
- Each retained destination has exactly one successful run for every algorithm/repetition pair, with matching duration, sampling interval, and kernel.
- Every successful run has 50 samples. Recorded durations span 10.000132–10.001154 seconds.
- Successive acknowledged-byte and retransmission counters agree with the recorded deltas. Sample timestamps and intervals agree within their six-decimal CSV rounding.
- Sample goodput agrees with byte deltas and actual elapsed time, accounting for that rounding. All rates are finite and nonnegative; no zero-goodput samples were observed.
- Independent calculations from raw CSVs agree with all per-run summaries and all 12 destination/algorithm aggregate means and sample standard deviations.
- Both representative-destination figures were visually checked: four labeled algorithms, three repetitions each, and consistent metric scales.
- Twelve deterministic Python tests and 23 C test groups passed before collection. Recorded source and build-artifact checksums still match; the default system algorithm remains BBR.

## Files

- [Manifest and exact test order](manifest.json), [client log](experiment.log), and [executed command](command.txt). The existing installed Python environment supplied dependencies; all application code came from `assignment3`.
- [Automated verification results](verification.json), [source/build checksums](source-checksums.json), and [toolchain versions](toolchain.json).
- [Comparison PDF](reports/algorithm-comparison-report.pdf) and [aggregate statistics](reports/destination-algorithm-statistics.csv).
- [Per-test statistics](reports/per-test-statistics.csv) include successful partial groups with `matched_destination=False`; the aggregate CSV excludes those groups.
- [Time-series plots](plots/algorithm-metrics-over-time.pdf) and [scatter plots](plots/algorithm-metrics-vs-goodput.pdf). Raw samples and metadata are in `tcp-traces`.

## Points for the oral evaluation

- The 0.2-second Python sampling interval controls logging. The eBPF policy makes decisions once per eligible RTT using its own ACK accounting.
- Per-run throughput is total acknowledged-byte progress divided by total actual sampled time, converted with 8 / 1e6. Destination statistics average three run rates; spread is sample standard deviation across those runs.
- A single failed test excludes the whole candidate group from matched comparisons. This keeps the algorithm/repetition counts equal, while preserving successful partial measurements.
- Retransmissions are a loss proxy. These sequential public-server tests do not establish fairness, convergence, a causal explanation of every window change, or every recovery corner case. Exact order and failures remain available for interpreting the results honestly.

Step 10 is complete with no remaining collection blocker. No additional transfers were run. The final assignment writeup and explanation of observed differences remain step 11.
