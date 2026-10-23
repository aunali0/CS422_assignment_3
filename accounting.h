#ifndef A3_ACCOUNTING_H
#define A3_ACCOUNTING_H

#define A3_US_PER_SECOND 1000000ULL

struct a3_accounting {
    __u64 interval_start_us;
    __u64 interval_start_bytes;
    __u64 previous_goodput; /* bytes/second */
    __u64 acked_segments;
    __u32 min_rtt_us;
    __u32 interval_rtt_us;
    __u8 previous_valid;
    __u8 interval_active;
    __u8 interval_limited;
};

struct a3_sample {
    __u64 elapsed_us;
    __u64 acked_bytes;
    __u64 acked_segments;
    __u64 goodput; /* bytes/second */
    __u64 previous_goodput; /* bytes/second */
    __u8 previous_valid;
};

/* Keep the connection's minimum RTT when discarding interval history. */
static inline void a3_reset_interval(struct a3_accounting *state)
{
    state->previous_goodput = 0;
    state->previous_valid = 0;
    state->interval_active = 0;
    state->interval_limited = 0;
    state->acked_segments = 0;
}

static inline void a3_start_interval(struct a3_accounting *state, __u64 now_us,
                                     __u64 bytes_acked, __u32 rtt_us, bool limited)
{
    state->interval_start_us = now_us;
    state->interval_start_bytes = bytes_acked;
    state->interval_rtt_us = rtt_us;
    state->interval_active = 1;
    state->interval_limited = limited;
    state->acked_segments = 0;
}

static inline void a3_record_ack(struct a3_accounting *state, __s32 rtt_us,
                                 __u32 acked_segments, bool limited)
{
    if (rtt_us > 0 && (!state->min_rtt_us || (__u32)rtt_us < state->min_rtt_us))
        state->min_rtt_us = rtt_us;

    if (state->interval_active) {
        state->acked_segments += acked_segments;
        state->interval_limited |= limited;
    }
}

/* Return one completed sample, or false while warming up/waiting/skipping. */
static inline bool a3_measure(struct a3_accounting *state, __u64 now_us,
                              __u64 bytes_acked, __u32 rtt_us, bool limited,
                              struct a3_sample *sample)
{
    *sample = (struct a3_sample){0};
    if (!state->min_rtt_us || !rtt_us) {
        a3_reset_interval(state);
        return false;
    }
    if (!state->interval_active) {
        a3_start_interval(state, now_us, bytes_acked, rtt_us, limited);
        return false;
    }
    if (now_us <= state->interval_start_us || bytes_acked < state->interval_start_bytes) {
        a3_reset_interval(state);
        return false;
    }

    state->interval_limited |= limited;
    __u64 elapsed_us = now_us - state->interval_start_us;
    __u64 acked_bytes = bytes_acked - state->interval_start_bytes;
    if (elapsed_us < state->interval_rtt_us || !acked_bytes)
        return false;

    if (state->interval_limited) {
        a3_reset_interval(state);
        a3_start_interval(state, now_us, bytes_acked, rtt_us, limited);
        return false;
    }
    if (acked_bytes > ~(__u64)0 / A3_US_PER_SECOND) {
        a3_reset_interval(state);
        return false;
    }

    sample->elapsed_us = elapsed_us;
    sample->acked_bytes = acked_bytes;
    sample->acked_segments = state->acked_segments;
    sample->goodput = acked_bytes * A3_US_PER_SECOND / elapsed_us;
    sample->previous_goodput = state->previous_goodput;
    sample->previous_valid = state->previous_valid;

    state->previous_goodput = sample->goodput;
    state->previous_valid = 1;
    a3_start_interval(state, now_us, bytes_acked, rtt_us, limited);
    return true;
}

#endif
