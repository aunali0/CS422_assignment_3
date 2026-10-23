#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>

#include "recovery.h"

#define TCP_CONG_NON_RESTRICTED (1U << 0)

_Static_assert(sizeof(struct a3_state) <=
               sizeof(((struct inet_connection_sock *)0)->icsk_ca_priv),
               "Controller state must fit in the socket's private area");

static inline struct a3_state *state_for(struct sock *sk)
{
    struct tcp_sock *tp = (void *)sk;

    return (void *)tp->inet_conn.icsk_ca_priv;
}

static inline bool is_limited(struct tcp_sock *tp)
{
    return tp->app_limited || tp->chrono_type == TCP_CHRONO_SNDBUF_LIMITED ||
           tp->chrono_type == TCP_CHRONO_RWND_LIMITED;
}

SEC("struct_ops")
void BPF_PROG(a3_init, struct sock *sk)
{
    struct tcp_sock *tp = (void *)sk;
    struct a3_window window = {
        .cwnd = tp->snd_cwnd,
        .ssthresh = tp->snd_ssthresh,
        .clamp = tp->snd_cwnd_clamp,
    };

    a3_init_window(state_for(sk), &window);
    tp->snd_cwnd = window.cwnd;
    tp->snd_ssthresh = window.ssthresh;
}

SEC("struct_ops")
void BPF_PROG(a3_pkts_acked, struct sock *sk, const struct ack_sample *sample)
{
    struct tcp_sock *tp = (void *)sk;
    struct a3_accounting *state = &state_for(sk)->accounting;

    if (sk->__sk_common.skc_state != TCP_ESTABLISHED)
        return;

    a3_record_ack(state, sample->rtt_us, sample->pkts_acked, is_limited(tp));
    if (a3_in_recovery(tp->inet_conn.icsk_ca_state))
        a3_reset_interval(state);
}

SEC("struct_ops")
__u32 BPF_PROG(a3_ssthresh, struct sock *sk)
{
    struct tcp_sock *tp = (void *)sk;

    return a3_loss_threshold(tp->snd_cwnd);
}

SEC("struct_ops")
void BPF_PROG(a3_set_state, struct sock *sk, __u8 new_state)
{
    struct tcp_sock *tp = (void *)sk;

    /* Linux stores new_state in the socket after this callback returns. */
    a3_change_state(state_for(sk), tp->inet_conn.icsk_ca_state, new_state);
}

SEC("struct_ops")
void BPF_PROG(a3_cwnd_event, struct sock *sk, enum tcp_ca_event event)
{
    struct tcp_sock *tp = (void *)sk;

    if (event == CA_EVENT_CWND_RESTART || event == CA_EVENT_TX_START)
        a3_on_restart(state_for(sk), event == CA_EVENT_CWND_RESTART, is_limited(tp));
}

SEC("struct_ops")
void BPF_PROG(a3_cong_avoid, struct sock *sk, __u32 ack, __u32 acked)
{
    struct tcp_sock *tp = (void *)sk;
    struct a3_state *state = state_for(sk);
    struct a3_sample sample;

    /* Normal growth uses interval ACK credit, not this callback's ACK count. */
    (void)ack;
    (void)acked;
    if (sk->__sk_common.skc_state != TCP_ESTABLISHED) {
        a3_reset_interval(&state->accounting);
        return;
    }
    if (!a3_normal_allowed(state, tp->inet_conn.icsk_ca_state))
        return;

    __u32 rtt_us = tp->srtt_us >> 3;
    if (a3_measure(&state->accounting, bpf_ktime_get_ns() / 1000,
                   tp->bytes_acked, rtt_us,
                   is_limited(tp) || !tp->is_cwnd_limited, &sample)) {
        struct a3_window window = {
            .cwnd = tp->snd_cwnd,
            .ssthresh = tp->snd_ssthresh,
            .clamp = tp->snd_cwnd_clamp,
        };

        a3_update_window(state, &window, rtt_us, &sample);
        tp->snd_cwnd = window.cwnd;
        tp->snd_ssthresh = window.ssthresh;
    }
}

SEC("struct_ops")
__u32 BPF_PROG(a3_undo_cwnd, struct sock *sk)
{
    struct tcp_sock *tp = (void *)sk;

    return a3_undo_window(state_for(sk), tp->snd_cwnd, tp->prior_cwnd);
}

SEC(".struct_ops.link")
struct tcp_congestion_ops a3_cc = {
    .init = (void *)a3_init,
    .pkts_acked = (void *)a3_pkts_acked,
    .ssthresh = (void *)a3_ssthresh,
    .set_state = (void *)a3_set_state,
    .cwnd_event = (void *)a3_cwnd_event,
    .cong_avoid = (void *)a3_cong_avoid,
    .undo_cwnd = (void *)a3_undo_cwnd,
    .flags = TCP_CONG_NON_RESTRICTED,
    .name = "a3_cc",
};

char LICENSE[] SEC("license") = "GPL";
