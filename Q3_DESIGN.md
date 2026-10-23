# Q3(b): RTT, goodput, and loss based window control

This is the selected proposal for Assignment 2, Question 3(b), and the starting
point for Assignment 3. It has not been implemented or evaluated. The saved
experiments compare CUBIC, Reno, and BBR; they do not test this controller.

## Idea

Use three signals with clear roles:

- Loss: reduce the sending window through Linux's recovery mechanism.
- RTT: grow cautiously when delay is low; hold when delay is moderately higher.
- Goodput: when RTT is high, reduce the window if delivery is no longer improving.

The measurements motivate this combination. Dallas showed that a much larger
window did not necessarily increase throughput. Netfiber had a slow run with many
retransmissions. The IP destination had a brief stall with a large RTT increase.
These observations motivate the rules, but do not prove that they will perform well.

## State and measurements

Start with an initial window of 10 segments, subject to the TCP stack's limits.
Start in slow start, with the slow-start threshold initially unlimited. Keep the
lowest valid RTT measured since connecting and the previous eligible interval's
goodput. Goodput is newly acknowledged application bytes divided by actual elapsed
seconds. Use the socket's smoothed RTT for window decisions; use seconds consistently.

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

The normal decision rule does not replace the stack's timeout window, which can
be one segment. The kernel implementation must map loss and timeout handling to
callbacks without requesting two reductions for the same event. ACK accounting
must count newly acknowledged data rather than the number of ACK messages.

## Choices and limitations

The 10% and 25% delay thresholds leave a range where the sender holds its window.
The 10% delay reduction is milder than the loss response. These are initial values
for experiments, not tuned settings. The normal update should increase by at most
one segment per RTT in congestion avoidance.

The delay and throughput decisions need only a minimum RTT and the previous
eligible interval's goodput. The minimum cannot adapt upward after a route change.
One-interval goodput comparisons can be noisy, and a single low RTT can make the
baseline too optimistic. These are limitations to evaluate.

With similar RTTs and a shared bottleneck, additive growth and loss reductions
may help flows share bandwidth. Flows with shorter RTTs update more often, and
this delay-sensitive controller may yield to Reno or CUBIC. Repeated increases
and reductions may produce oscillation; neither fairness nor convergence has
been demonstrated. Compare throughput, RTT, retransmissions, and recovery behavior
against the three baselines before making performance claims.
