#ifndef A3_RECOVERY_H
#define A3_RECOVERY_H

#include "window.h"

static inline bool a3_in_recovery(__u8 ca_state)
{
    return ca_state >= TCP_CA_CWR;
}

/* Return a threshold; Linux decides when and how to change its actual window. */
static inline __u32 a3_loss_threshold(__u32 cwnd)
{
    __u32 threshold = cwnd / 2;

    return threshold < 2 ? 2 : threshold;
}

static inline void a3_change_state(struct a3_state *state, __u8 old_state,
                                   __u8 new_state)
{
    if (new_state == TCP_CA_Loss)
        state->slow_start = 1;
    else if (new_state == TCP_CA_CWR || new_state == TCP_CA_Recovery)
        state->slow_start = 0;
    else if (!a3_in_recovery(old_state))
        return;

    a3_reset_interval(&state->accounting);
}

static inline bool a3_normal_allowed(struct a3_state *state, __u8 ca_state)
{
    if (!a3_in_recovery(ca_state))
        return true;

    a3_reset_interval(&state->accounting);
    return false;
}

/* Called only for window-restart or transmission-start notifications. */
static inline void a3_on_restart(struct a3_state *state, bool cwnd_restart,
                                 bool limited)
{
    if (cwnd_restart || limited || state->accounting.interval_limited)
        a3_reset_interval(&state->accounting);
}

static inline __u32 a3_undo_window(struct a3_state *state, __u32 cwnd,
                                   __u32 prior_cwnd)
{
    a3_reset_interval(&state->accounting);
    return cwnd > prior_cwnd ? cwnd : prior_cwnd;
}

#endif
