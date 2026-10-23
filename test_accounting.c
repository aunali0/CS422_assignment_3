#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <linux/types.h>

#include "accounting.h"

static void test_units_and_previous_goodput(void)
{
    struct a3_accounting state = {0};
    struct a3_sample sample;

    a3_record_ack(&state, 100000, 1, false);
    assert(!a3_measure(&state, 1000000, 5000, 100000, false, &sample));
    a3_record_ack(&state, 120000, 2, false);
    assert(a3_measure(&state, 1100000, 6000, 100000, false, &sample));
    assert(sample.elapsed_us == 100000 && sample.acked_bytes == 1000);
    assert(sample.acked_segments == 2 && sample.goodput == 10000);
    assert(!sample.previous_valid);

    a3_record_ack(&state, 90000, 4, false);
    assert(a3_measure(&state, 1350000, 11000, 100000, false, &sample));
    assert(state.min_rtt_us == 90000);
    assert(sample.elapsed_us == 250000 && sample.acked_bytes == 5000);
    assert(sample.goodput == 20000);
    assert(sample.previous_valid && sample.previous_goodput == 10000);
    assert(state.previous_goodput == 20000 && state.previous_valid);

    struct a3_accounting large = {.min_rtt_us = 100};
    __u64 baseline = 1ULL << 40;
    assert(!a3_measure(&large, baseline, baseline, 100, false, &sample));
    assert(a3_measure(&large, baseline + 100, baseline + 1000, 100, false, &sample));
    assert(sample.goodput == 10000000 && sample.acked_bytes == 1000);
}

static void test_invalid_rtt(void)
{
    struct a3_accounting state = {0};
    struct a3_sample sample;

    a3_record_ack(&state, -1, 0, false);
    a3_record_ack(&state, 0, 0, false);
    assert(state.min_rtt_us == 0);
    assert(!a3_measure(&state, 1000, 100, 100, false, &sample));
    assert(!state.interval_active);

    a3_record_ack(&state, 100, 0, false);
    a3_record_ack(&state, -1, 0, false);
    a3_record_ack(&state, 200, 0, false);
    assert(state.min_rtt_us == 100);
    assert(!a3_measure(&state, 1000, 100, 100, false, &sample));
    assert(a3_measure(&state, 1100, 200, 100, false, &sample));
    assert(!a3_measure(&state, 1200, 300, 0, false, &sample));
    assert(state.min_rtt_us == 100 && !state.interval_active && !state.previous_valid);
}

static void test_zero_ack_progress(void)
{
    struct a3_accounting state = {.min_rtt_us = 100};
    struct a3_sample sample;

    assert(!a3_measure(&state, 1000, 500, 100, false, &sample));
    assert(a3_measure(&state, 1100, 600, 100, false, &sample));
    assert(!a3_measure(&state, 1500, 600, 100, false, &sample));
    assert(state.interval_start_us == 1100 && state.previous_valid);
    a3_record_ack(&state, 100, 1, false);
    assert(a3_measure(&state, 1600, 700, 100, false, &sample));
    assert(sample.elapsed_us == 500 && sample.acked_bytes == 100);
    assert(sample.goodput == 200000);
}

static void test_once_per_rtt(void)
{
    struct a3_accounting state = {.min_rtt_us = 100};
    struct a3_sample sample;

    assert(!a3_measure(&state, 1000, 0, 100, false, &sample));
    a3_record_ack(&state, 100, 2, false);
    assert(!a3_measure(&state, 1050, 200, 200, false, &sample));
    a3_record_ack(&state, 100, 3, false);
    assert(!a3_measure(&state, 1099, 500, 200, false, &sample));
    assert(a3_measure(&state, 1100, 500, 200, false, &sample));
    assert(sample.acked_segments == 5 && sample.acked_bytes == 500);
    assert(state.interval_rtt_us == 200 && state.acked_segments == 0);
    a3_record_ack(&state, 100, 1, false);
    assert(!a3_measure(&state, 1200, 600, 50, false, &sample));
    a3_record_ack(&state, 100, 1, false);
    assert(a3_measure(&state, 1300, 700, 50, false, &sample));
    assert(sample.acked_bytes == 200 && sample.acked_segments == 2);
    assert(state.interval_rtt_us == 50);
    assert(!a3_measure(&state, 1301, 800, 50, false, &sample));
}

static void test_resets(void)
{
    struct a3_accounting state = {.min_rtt_us = 100};
    struct a3_sample sample;

    assert(!a3_measure(&state, 1000, 100, 100, false, &sample));
    assert(a3_measure(&state, 1100, 200, 100, false, &sample));
    a3_record_ack(&state, 100, 3, true);
    a3_reset_interval(&state);
    assert(state.min_rtt_us == 100 && !state.interval_active);
    assert(!state.previous_valid && !state.interval_limited && state.acked_segments == 0);
    assert(!a3_measure(&state, 5000, 10000, 100, false, &sample));
    a3_record_ack(&state, 100, 1, false);
    assert(a3_measure(&state, 5100, 10100, 100, false, &sample));
    assert(!sample.previous_valid && sample.acked_bytes == 100 && sample.acked_segments == 1);
}

static void test_invalid_time_and_counters(void)
{
    struct a3_accounting state = {.min_rtt_us = 100};
    struct a3_sample sample;

    assert(!a3_measure(&state, 1000, 500, 100, false, &sample));
    assert(!a3_measure(&state, 1000, 600, 100, false, &sample));
    assert(!state.interval_active);
    assert(!a3_measure(&state, 2000, 500, 100, false, &sample));
    assert(!a3_measure(&state, 1999, 600, 100, false, &sample));
    assert(!state.interval_active);
    assert(!a3_measure(&state, 3000, 500, 100, false, &sample));
    assert(!a3_measure(&state, 3100, 499, 100, false, &sample));
    assert(!state.interval_active && !state.previous_valid);
    assert(!a3_measure(&state, 4000, 0, 100, false, &sample));
    assert(!a3_measure(&state, 4100, ~(__u64)0, 100, false, &sample));
    assert(!state.interval_active && !state.previous_valid);
}

static void test_limited_intervals(void)
{
    struct a3_accounting state = {.min_rtt_us = 100};
    struct a3_sample sample;

    assert(!a3_measure(&state, 1000, 0, 100, false, &sample));
    assert(a3_measure(&state, 1100, 100, 100, false, &sample));
    a3_record_ack(&state, 100, 1, true);
    assert(!a3_measure(&state, 1150, 200, 100, false, &sample));
    assert(!a3_measure(&state, 1200, 300, 100, false, &sample));
    assert(!state.previous_valid && state.acked_segments == 0);
    a3_record_ack(&state, 100, 1, false);
    assert(a3_measure(&state, 1300, 400, 100, false, &sample));
    assert(!sample.previous_valid && sample.acked_bytes == 100);
    assert(!a3_measure(&state, 1400, 500, 100, true, &sample));
    assert(!state.previous_valid);
}

static void test_independent_connections(void)
{
    struct a3_accounting first = {0}, second = {0};
    struct a3_sample sample;

    a3_record_ack(&first, 100, 1, false);
    a3_record_ack(&second, 200, 2, false);
    assert(!a3_measure(&first, 1000, 100, 100, false, &sample));
    assert(!a3_measure(&second, 1050, 500, 200, false, &sample));
    a3_record_ack(&first, 90, 3, false);
    assert(a3_measure(&first, 1100, 400, 100, false, &sample));
    assert(first.previous_valid && !second.previous_valid);
    assert(second.min_rtt_us == 200 && second.interval_start_bytes == 500);
    a3_record_ack(&second, 180, 4, false);
    assert(a3_measure(&second, 1250, 1500, 200, false, &sample));
    assert(sample.goodput == 5000000 && sample.acked_segments == 4);
    a3_reset_interval(&first);
    assert(second.previous_valid && second.min_rtt_us == 180);
    assert(second.interval_start_us == 1250);
}

int main(void)
{
    test_units_and_previous_goodput();
    test_invalid_rtt();
    test_zero_ack_progress();
    test_once_per_rtt();
    test_resets();
    test_invalid_time_and_counters();
    test_limited_intervals();
    test_independent_connections();
    puts("Accounting checks passed (8 groups).");
    return 0;
}
