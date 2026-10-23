#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <linux/tcp.h>

#include "recovery.h"

static struct a3_state busy_state(void)
{
    return (struct a3_state){
        .accounting = {
            .interval_start_us = 1000,
            .interval_start_bytes = 100,
            .previous_goodput = 1000000,
            .acked_segments = 3,
            .min_rtt_us = 100,
            .interval_rtt_us = 100,
            .previous_valid = 1,
            .interval_active = 1,
            .interval_limited = 1,
        },
        .slow_start = 1,
    };
}

static void assert_history_cleared(const struct a3_state *state)
{
    assert(state->accounting.min_rtt_us == 100);
    assert(!state->accounting.previous_valid && !state->accounting.interval_active);
    assert(!state->accounting.interval_limited && state->accounting.acked_segments == 0);
    assert(state->accounting.previous_goodput == 0);
}

static void test_loss_episode(void)
{
    struct a3_state state = busy_state();
    struct a3_window window = {.cwnd = 101, .ssthresh = 200, .clamp = 1000};

    __u32 threshold = a3_loss_threshold(window.cwnd);
    assert(threshold == 50 && a3_loss_threshold(window.cwnd) == 50);
    assert(window.cwnd == 101 && window.ssthresh == 200);
    a3_change_state(&state, TCP_CA_Open, TCP_CA_Recovery);
    assert(!state.slow_start);
    assert_history_cleared(&state);
    assert(window.cwnd == 101); /* Notification does not apply a reduction. */

    /* Stand in for Linux completing recovery; this is not a PRR simulation. */
    window.ssthresh = threshold;
    window.cwnd = threshold;
    a3_change_state(&state, TCP_CA_Recovery, TCP_CA_Recovery);
    a3_change_state(&state, TCP_CA_Recovery, TCP_CA_Recovery);
    assert(window.cwnd == 50 && window.ssthresh == 50);
    assert(!state.slow_start);
    assert_history_cleared(&state);

    a3_change_state(&state, TCP_CA_Recovery, TCP_CA_Open);
    assert(!state.slow_start);
    assert(a3_loss_threshold(window.cwnd) == 25); /* A later, separate episode. */
    assert(a3_loss_threshold(3) == 2 && a3_loss_threshold(1) == 2);
    assert(a3_loss_threshold(~(__u32)0) == (~(__u32)0 / 2));
}

static void test_state_transitions(void)
{
    struct a3_state state = busy_state();

    a3_change_state(&state, TCP_CA_Open, TCP_CA_Disorder);
    a3_change_state(&state, TCP_CA_Disorder, TCP_CA_Open);
    assert(state.accounting.previous_valid && state.accounting.acked_segments == 3);
    assert(state.slow_start);

    a3_change_state(&state, TCP_CA_Open, TCP_CA_CWR);
    assert(!state.slow_start);
    assert_history_cleared(&state);
    a3_change_state(&state, TCP_CA_CWR, TCP_CA_Recovery);
    assert(!state.slow_start);
    assert_history_cleared(&state);
    a3_change_state(&state, TCP_CA_Recovery, TCP_CA_Loss);
    assert(state.slow_start);
    assert_history_cleared(&state);
    a3_change_state(&state, TCP_CA_Loss, TCP_CA_Disorder);
    assert(state.slow_start);
    assert_history_cleared(&state);

    state = busy_state();
    state.slow_start = 0;
    a3_change_state(&state, TCP_CA_CWR, TCP_CA_Open);
    assert(!state.slow_start);
    assert_history_cleared(&state);
}

/* Follow the production guard, accounting, and normal-decision sequence. */
static bool on_ack(struct a3_state *state, struct a3_window *window, __u8 ca_state,
                   __u64 now_us, __u64 bytes)
{
    struct a3_sample sample;

    a3_record_ack(&state->accounting, 100, 1, false);
    if (!a3_normal_allowed(state, ca_state))
        return false;
    if (!a3_measure(&state->accounting, now_us, bytes, 100, false, &sample))
        return false;
    a3_update_window(state, window, 100, &sample);
    return true;
}

static void test_timeout_and_resume(void)
{
    struct a3_state state = busy_state();
    struct a3_window window = {.cwnd = 100, .ssthresh = 200, .clamp = 1000};

    state.slow_start = 0;
    window.ssthresh = a3_loss_threshold(window.cwnd);
    window.cwnd = 1; /* A window chosen by Linux, not by our notification. */
    a3_change_state(&state, TCP_CA_Open, TCP_CA_Loss);
    a3_change_state(&state, TCP_CA_Loss, TCP_CA_Loss);
    assert(state.slow_start && window.cwnd == 1 && window.ssthresh == 50);
    assert_history_cleared(&state);
    assert(!on_ack(&state, &window, TCP_CA_Loss, 5000, 5000));
    assert(window.cwnd == 1 && window.ssthresh == 50);
    assert_history_cleared(&state);

    a3_change_state(&state, TCP_CA_Loss, TCP_CA_Open);
    assert(!on_ack(&state, &window, TCP_CA_Open, 6000, 6000));
    assert(window.cwnd == 1 && !state.accounting.previous_valid);
    assert(!on_ack(&state, &window, TCP_CA_Open, 6099, 6100));
    assert(window.cwnd == 1);
    assert(on_ack(&state, &window, TCP_CA_Open, 6100, 6200));
    assert(window.cwnd == 2 && state.slow_start);
    assert(state.accounting.previous_goodput == 2000000);
}

static void test_recovery_guard(void)
{
    const __u8 states[] = {TCP_CA_CWR, TCP_CA_Recovery, TCP_CA_Loss};

    for (unsigned int i = 0; i < sizeof(states) / sizeof(states[0]); i++) {
        struct a3_state state = busy_state();
        struct a3_window window = {.cwnd = 1, .ssthresh = 50, .clamp = 1000};

        state.accounting.interval_limited = 0; /* Otherwise ready for normal growth. */
        assert(!on_ack(&state, &window, states[i], 1000000, 1000000));
        assert(window.cwnd == 1 && window.ssthresh == 50);
        assert_history_cleared(&state);
    }

    struct a3_state state = busy_state();
    assert(a3_normal_allowed(&state, TCP_CA_Open));
    assert(a3_normal_allowed(&state, TCP_CA_Disorder));
    assert(state.accounting.previous_valid);
}

static void test_undo(void)
{
    struct a3_state state = busy_state();
    __u32 cwnd = 10;

    state.slow_start = 0;
    assert(a3_undo_window(&state, cwnd, 20) == 20);
    assert(cwnd == 10 && !state.slow_start); /* Linux applies the returned value. */
    assert_history_cleared(&state);
    assert(a3_undo_window(&state, 30, 20) == 30);
    assert(a3_undo_window(&state, 20, 20) == 20);
    assert(a3_undo_window(&state, 1, 1) == 1);
    assert(a3_undo_window(&state, 1, ~(__u32)0) == ~(__u32)0);
}

static void test_restarts(void)
{
    struct a3_state state = busy_state();

    state.accounting.interval_limited = 0;
    a3_on_restart(&state, false, false);
    assert(state.accounting.previous_valid); /* Zero in flight is not enough. */
    a3_on_restart(&state, false, true);
    assert_history_cleared(&state);
    assert(state.slow_start);

    state = busy_state();
    a3_on_restart(&state, false, false); /* A limitation observed earlier. */
    assert_history_cleared(&state);

    state = busy_state();
    state.slow_start = 0;
    state.accounting.interval_limited = 0;
    a3_on_restart(&state, true, false); /* Linux reports a window restart. */
    assert_history_cleared(&state);
    assert(!state.slow_start);
}

static void test_independent_connections(void)
{
    struct a3_state first = busy_state(), second = busy_state();

    a3_change_state(&first, TCP_CA_Open, TCP_CA_Recovery);
    assert(!first.slow_start && second.slow_start);
    assert(second.accounting.previous_valid && second.accounting.acked_segments == 3);
    a3_change_state(&second, TCP_CA_Open, TCP_CA_Loss);
    assert(second.slow_start && !first.slow_start);
    assert_history_cleared(&first);
    assert_history_cleared(&second);
}

int main(void)
{
    test_loss_episode();
    test_state_transitions();
    test_timeout_and_resume();
    test_recovery_guard();
    test_undo();
    test_restarts();
    test_independent_connections();
    puts("Recovery checks passed (7 groups).");
    return 0;
}
