#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <linux/types.h>

#include "window.h"

static void test_initialization(void)
{
    struct a3_state state = {.accounting = {.previous_valid = 1}};
    struct a3_window window = {.cwnd = 20, .ssthresh = 5, .clamp = 100};

    a3_init_window(&state, &window);
    assert(state.slow_start && !state.accounting.previous_valid);
    assert(window.cwnd == 10 && window.ssthresh == A3_INFINITE_SSTHRESH);
    window.cwnd = 5;
    a3_init_window(&state, &window);
    assert(window.cwnd == 5);
    window.cwnd = 10;
    window.clamp = 4;
    a3_init_window(&state, &window);
    assert(window.cwnd == 4);
    window.cwnd = 1;
    a3_init_window(&state, &window);
    assert(window.cwnd == 1);
}

static void test_startup_and_congestion_avoidance(void)
{
    struct a3_state state = {.accounting = {.min_rtt_us = 100}, .slow_start = 1};
    struct a3_window window = {.cwnd = 10, .ssthresh = 1000, .clamp = 1000};
    struct a3_sample sample = {.acked_segments = 3};

    a3_update_window(&state, &window, 110, &sample);
    assert(window.cwnd == 13 && state.slow_start);
    sample.acked_segments = 100;
    a3_update_window(&state, &window, 100, &sample);
    assert(window.cwnd == 26); /* At most doubles, even with many ACKs. */
    window.ssthresh = window.cwnd;
    a3_update_window(&state, &window, 100, &sample);
    assert(window.cwnd == 27 && !state.slow_start);
    window.ssthresh = 1000;
    a3_update_window(&state, &window, 100, &sample);
    assert(window.cwnd == 28 && !state.slow_start);

    state.slow_start = 1;
    window.cwnd = 10;
    a3_update_window(&state, &window, 111, &sample);
    assert(window.cwnd == 10 && !state.slow_start);
}

static void test_delay_boundaries(void)
{
    struct a3_state state = {.accounting = {.min_rtt_us = 100}};
    struct a3_window window = {.cwnd = 100, .ssthresh = 100, .clamp = 1000};
    struct a3_sample sample = {.goodput = 500, .previous_goodput = 500, .previous_valid = 1};

    a3_update_window(&state, &window, 110, &sample);
    assert(window.cwnd == 101);
    a3_update_window(&state, &window, 111, &sample);
    assert(window.cwnd == 101);
    a3_update_window(&state, &window, 125, &sample);
    assert(window.cwnd == 101);
    a3_update_window(&state, &window, 126, &sample);
    assert(window.cwnd == 90 && window.ssthresh == 90);

    state.accounting.min_rtt_us = 101;
    window.cwnd = 100;
    a3_update_window(&state, &window, 111, &sample);
    assert(window.cwnd == 101);
    a3_update_window(&state, &window, 112, &sample);
    assert(window.cwnd == 101);
    a3_update_window(&state, &window, 126, &sample);
    assert(window.cwnd == 101);
    a3_update_window(&state, &window, 127, &sample);
    assert(window.cwnd == 90);
}

static void test_goodput_condition(void)
{
    struct a3_state state = {.accounting = {.min_rtt_us = 100}};
    struct a3_window window = {.cwnd = 100, .ssthresh = 200, .clamp = 1000};
    struct a3_sample sample = {.goodput = 500, .previous_goodput = 500};

    a3_update_window(&state, &window, 150, &sample);
    assert(window.cwnd == 100 && window.ssthresh == 200);
    sample.previous_valid = 1;
    sample.goodput = 501;
    a3_update_window(&state, &window, 150, &sample);
    assert(window.cwnd == 100 && window.ssthresh == 200);
    sample.goodput = 500;
    a3_update_window(&state, &window, 150, &sample);
    assert(window.cwnd == 90 && window.ssthresh == 90);
    sample.goodput = 499;
    a3_update_window(&state, &window, 150, &sample);
    assert(window.cwnd == 81 && window.ssthresh == 81);
}

static void test_window_limits(void)
{
    struct a3_state state = {.accounting = {.min_rtt_us = 100}, .slow_start = 1};
    struct a3_window window = {.cwnd = 10, .ssthresh = 1000, .clamp = 15};
    struct a3_sample sample = {.acked_segments = 100, .previous_valid = 1};

    a3_update_window(&state, &window, 100, &sample);
    assert(window.cwnd == 15);
    state.slow_start = 0;
    a3_update_window(&state, &window, 100, &sample);
    assert(window.cwnd == 15);
    window.cwnd = 3;
    a3_update_window(&state, &window, 150, &sample);
    assert(window.cwnd == 2 && window.ssthresh == 2);
    a3_update_window(&state, &window, 150, &sample);
    assert(window.cwnd == 2);
    window.cwnd = 1;
    a3_update_window(&state, &window, 120, &sample);
    assert(window.cwnd == 1); /* Holding does not impose a minimum of two. */
    window.clamp = 1;
    a3_update_window(&state, &window, 150, &sample);
    assert(window.cwnd == 1 && window.ssthresh == 1);

    window.cwnd = ~(__u32)0 - 1;
    window.clamp = ~(__u32)0;
    a3_update_window(&state, &window, 100, &sample);
    assert(window.cwnd == ~(__u32)0);
    a3_update_window(&state, &window, 100, &sample);
    assert(window.cwnd == ~(__u32)0);
    state.slow_start = 1;
    window.cwnd = 2000000000U;
    window.ssthresh = ~(__u32)0;
    sample.acked_segments = ~(__u64)0;
    a3_update_window(&state, &window, 100, &sample);
    assert(window.cwnd == 4000000000U);
    state.accounting.min_rtt_us = ~(__u32)0;
    state.slow_start = 0;
    a3_update_window(&state, &window, ~(__u32)0, &sample);
    assert(window.cwnd == 4000000001U);
}

/* Exercise accounting and decisions together, as the kernel callback does. */
static bool on_ack(struct a3_state *state, struct a3_window *window,
                   __u64 now_us, __u64 bytes, __u32 segments, bool limited)
{
    struct a3_sample sample;

    a3_record_ack(&state->accounting, 100, segments, limited);
    if (!a3_measure(&state->accounting, now_us, bytes, 100, limited, &sample))
        return false;
    a3_update_window(state, window, 100, &sample);
    return true;
}

static void test_once_per_rtt(void)
{
    struct a3_state state = {.slow_start = 1};
    struct a3_window window = {.cwnd = 10, .ssthresh = 1000, .clamp = 1000};

    assert(!on_ack(&state, &window, 1000, 0, 0, false));
    assert(!on_ack(&state, &window, 1020, 100, 1, false));
    assert(!on_ack(&state, &window, 1050, 200, 1, false));
    assert(window.cwnd == 10);
    assert(on_ack(&state, &window, 1100, 300, 1, false));
    assert(window.cwnd == 13);
    assert(!on_ack(&state, &window, 1101, 400, 1, false));
    assert(window.cwnd == 13);
    state.slow_start = 0;
    assert(on_ack(&state, &window, 1500, 500, 1, false));
    assert(window.cwnd == 14); /* One increase despite several elapsed RTTs. */
    assert(!on_ack(&state, &window, 1501, 600, 1, false));
    assert(window.cwnd == 14);
}

static void test_limited_intervals(void)
{
    struct a3_state state = {.slow_start = 1};
    struct a3_window window = {.cwnd = 10, .ssthresh = 1000, .clamp = 1000};

    assert(!on_ack(&state, &window, 1000, 0, 0, false));
    assert(on_ack(&state, &window, 1100, 100, 1, false));
    assert(window.cwnd == 11 && state.accounting.previous_valid);
    assert(!on_ack(&state, &window, 1150, 200, 1, true));
    assert(!on_ack(&state, &window, 1200, 300, 1, false));
    assert(window.cwnd == 11 && state.slow_start && !state.accounting.previous_valid);
    assert(on_ack(&state, &window, 1300, 400, 1, false));
    assert(window.cwnd == 12 && state.slow_start);
    assert(!on_ack(&state, &window, 1400, 500, 1, true));
    assert(window.cwnd == 12 && !state.accounting.previous_valid);
}

static void test_previous_sample_used(void)
{
    struct a3_state state = {.accounting = {.min_rtt_us = 100}};
    struct a3_window window = {.cwnd = 100, .ssthresh = 200, .clamp = 1000};
    struct a3_sample sample;

    assert(!a3_measure(&state.accounting, 1000, 0, 150, false, &sample));
    assert(a3_measure(&state.accounting, 1150, 100, 150, false, &sample));
    a3_update_window(&state, &window, 150, &sample);
    assert(window.cwnd == 100); /* No previous eligible rate yet. */
    assert(a3_measure(&state.accounting, 1300, 300, 150, false, &sample));
    assert(state.accounting.previous_goodput == sample.goodput);
    a3_update_window(&state, &window, 150, &sample);
    assert(window.cwnd == 100); /* Improving rate must not compare with itself. */
    assert(a3_measure(&state.accounting, 1450, 500, 150, false, &sample));
    a3_update_window(&state, &window, 150, &sample);
    assert(window.cwnd == 90 && window.ssthresh == 90);
}

int main(void)
{
    test_initialization();
    test_startup_and_congestion_avoidance();
    test_delay_boundaries();
    test_goodput_condition();
    test_window_limits();
    test_once_per_rtt();
    test_limited_intervals();
    test_previous_sample_used();
    puts("Window checks passed (8 groups).");
    return 0;
}
