#ifndef A3_WINDOW_H
#define A3_WINDOW_H

#include "accounting.h"

/* Linux's sentinel for an initially unlimited slow-start threshold. */
#define A3_INFINITE_SSTHRESH 0x7fffffffU

struct a3_state {
    struct a3_accounting accounting;
    __u8 slow_start;
};

/* A temporary copy of the kernel's window values, not persistent state. */
struct a3_window {
    __u32 cwnd;
    __u32 ssthresh;
    __u32 clamp;
};

static inline void a3_init_window(struct a3_state *state, struct a3_window *window)
{
    *state = (struct a3_state){.slow_start = 1};
    if (window->cwnd > 10)
        window->cwnd = 10;
    if (window->cwnd > window->clamp)
        window->cwnd = window->clamp;
    window->ssthresh = A3_INFINITE_SSTHRESH;
}

/* Call only for a completed, eligible measurement interval outside recovery. */
static inline void a3_update_window(struct a3_state *state, struct a3_window *window,
                                    __u32 rtt_us, const struct a3_sample *sample)
{
    __u64 cwnd = window->cwnd;
    __u64 min_rtt_us = state->accounting.min_rtt_us;
    bool low_delay = 100ULL * rtt_us <= 110ULL * min_rtt_us;
    bool reduced = false;

    if (state->slow_start && cwnd < window->ssthresh && low_delay) {
        cwnd += sample->acked_segments < cwnd ? sample->acked_segments : cwnd;
    } else {
        state->slow_start = 0;
        if (100ULL * rtt_us > 125ULL * min_rtt_us && sample->previous_valid &&
            sample->goodput <= sample->previous_goodput) {
            cwnd = 9 * cwnd / 10;
            if (cwnd < 2)
                cwnd = 2;
            reduced = true;
        } else if (low_delay) {
            cwnd += 1;
        }
    }

    if (cwnd > window->clamp)
        cwnd = window->clamp;
    window->cwnd = cwnd;
    if (reduced)
        window->ssthresh = window->cwnd;
}

#endif
