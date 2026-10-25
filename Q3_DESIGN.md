# Q3(b): RTT, goodput, and loss based window control

This design was developed for Assignment 2, Question 3(b), and implemented as
`a3_cc` in Assignment 3. The Assignment 2 measurements motivated its rules;
the Assignment 3 experiments compare it with CUBIC, Reno, and BBR.

AI tools helped develop and simplify this design and refine its explanation.

## Idea

Use three signals with clear roles:

- Loss: reduce the sending window through Linux's recovery mechanism.
- RTT: grow cautiously when delay is low; hold when delay is moderately higher.
- Goodput: when RTT is high, reduce the window if delivery is no longer improving.

The measurements motivate this combination. Dallas showed that a much larger
window did not necessarily increase throughput. Netfiber had a slow run with many
retransmissions. The IP destination had a brief stall with a large RTT increase.
These observations motivated the rules; they do not establish an advantage over
the baseline algorithms.

## State and measurements

Start with an initial window of 10 segments, subject to the TCP stack's limits.
Start in slow start, with the slow-start threshold initially unlimited. Keep the
lowest valid RTT measured since connecting and the previous eligible interval's
goodput. Goodput is newly acknowledged application bytes divided by actual elapsed
time, expressed in bytes/s. Window decisions use the socket's smoothed RTT;
RTT comparisons use consistent time units.

Make one normal window decision per completed RTT with new ACK progress. During
recovery, leave sending and retransmissions to Linux. Also skip normal decisions
when the sender has no data ready or the receiver's window limits sending. Clear
the previous goodput when skipping an interval or restarting after recovery, so a
pause is not compared with a busy interval.

## Pseudocode

```text
State: slow_start = true; previous_goodput = unset
On a new loss-recovery episode:
    request ssthresh = max(2, floor(cwnd / 2))
    let Linux apply recovery once using that threshold
    slow_start = false; clear previous_goodput and interval accounting
On a retransmission timeout:
    let Linux apply its normal timeout window and recovery
    slow_start = true; clear previous_goodput and interval accounting
Once per RTT with new ACK progress, outside recovery:
    update minimum_RTT and measure goodput
    if application limited or receiver-window limited:
        clear previous_goodput; finish interval
    if slow_start and cwnd < ssthresh and RTT <= 1.10 * minimum_RTT:
        cwnd += min(newly_acked_segments, cwnd)
    else:
        slow_start = false
        if RTT > 1.25 * minimum_RTT and previous_goodput is valid
           and goodput <= previous_goodput:
            cwnd = max(2, floor(0.90 * cwnd)); ssthresh = cwnd
        else if RTT <= 1.10 * minimum_RTT:
            cwnd += 1
        else:
            hold cwnd
    obey the kernel window limit
    previous_goodput = goodput; finish interval
```

Linux handles timeout recovery and can reduce the window to one segment. The
controller supplies the loss threshold and resets interval history without applying
a second recovery reduction. ACK accounting counts newly acknowledged segments
rather than ACK messages.

## Choices and limitations

The 10% and 25% delay thresholds leave a range where the sender holds its window.
The 10% delay reduction is milder than the loss response. These thresholds are
heuristics, not tuned settings. Congestion avoidance increases the window by at
most one segment per eligible RTT.

The delay and throughput decisions need only a minimum RTT and the previous
eligible interval's goodput. The minimum cannot adapt upward after a route change.
One-interval goodput comparisons can be noisy, and a single low RTT can make the
baseline too optimistic.

With similar RTTs and a shared bottleneck, additive growth and loss reductions
may help flows share bandwidth. Flows with shorter RTTs update more often, and
this delay-sensitive controller may yield to Reno or CUBIC. Repeated increases
and reductions may produce oscillation. The saved single-flow experiments do not
establish fairness or convergence between competing flows.
