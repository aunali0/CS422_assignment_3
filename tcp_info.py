# Decoder for the Linux `struct tcp_info` returned by getsockopt(IPPROTO_TCP, TCP_INFO).
#
# Layout source: include/uapi/linux/tcp.h. The struct only ever grows by appending fields,
# so the table below describes a known 248-byte prefix: an older kernel returns a shorter
# buffer and its missing trailing fields decode as None instead of raising, while a newer
# kernel returns a longer buffer whose unknown tail is ignored. RunMetadata.tcp_info_bytes
# records how many bytes the kernel actually wrote, so a reader can tell which columns were
# available. The host kernel for these measurements (6.18.54.1-microsoft-standard-WSL2)
# returns 280 bytes -- 32 bytes of fields newer than this table, which are not decoded.
#
# On x86-64 every field below already sits at its natural alignment, so the struct has no
# interior padding and a packed ("=") decode reproduces the kernel layout exactly.
#
# Verified on the host kernel by decoding a live socket and comparing every field against
# `ss -ti` for the same socket (rtt/rttvar, mss, pmtu, cwnd, ssthresh, bytes_acked,
# bytes_sent, segs_out, data_segs_out, delivered, min_rtt, busy_time, retrans/total_retrans,
# rcv_space, rcv_ssthresh and snd_wnd all matched).

import socket
import struct

# (name, struct format code), in kernel declaration order.
TCP_INFO_FIELDS: tuple[tuple[str, str], ...] = (
    ("state", "B"),
    ("ca_state", "B"),
    ("retransmits", "B"),
    ("probes", "B"),
    ("backoff", "B"),
    ("options", "B"),
    ("wscale", "B"),  # snd_wscale:4, rcv_wscale:4
    ("app_limited", "B"),  # delivery_rate_app_limited:1, fastopen_client_fail:2
    ("rto", "I"),
    ("ato", "I"),
    ("snd_mss", "I"),
    ("rcv_mss", "I"),
    ("unacked", "I"),
    ("sacked", "I"),
    ("lost", "I"),
    ("retrans", "I"),
    ("fackets", "I"),
    ("last_data_sent", "I"),
    ("last_ack_sent", "I"),
    ("last_data_recv", "I"),
    ("last_ack_recv", "I"),
    ("pmtu", "I"),
    ("rcv_ssthresh", "I"),
    ("rtt", "I"),
    ("rttvar", "I"),
    ("snd_ssthresh", "I"),
    ("snd_cwnd", "I"),
    ("advmss", "I"),
    ("reordering", "I"),
    ("rcv_rtt", "I"),
    ("rcv_space", "I"),
    ("total_retrans", "I"),
    ("pacing_rate", "Q"),
    ("max_pacing_rate", "Q"),
    ("bytes_acked", "Q"),
    ("bytes_received", "Q"),
    ("segs_out", "I"),
    ("segs_in", "I"),
    ("notsent_bytes", "I"),
    ("min_rtt", "I"),
    ("data_segs_in", "I"),
    ("data_segs_out", "I"),
    ("delivery_rate", "Q"),
    ("busy_time", "Q"),
    ("rwnd_limited", "Q"),
    ("sndbuf_limited", "Q"),
    ("delivered", "I"),
    ("delivered_ce", "I"),
    ("bytes_sent", "Q"),
    ("bytes_retrans", "Q"),
    ("dsack_dups", "I"),
    ("reord_seen", "I"),
    ("rcv_ooopack", "I"),
    ("snd_wnd", "I"),
    ("rcv_wnd", "I"),
    ("rehash", "I"),
    ("total_rto", "H"),
    ("total_rto_recoveries", "H"),
    ("total_rto_time", "I"),
)

TCP_INFO_UNITS: dict[str, str] = {
    "state": "enum",
    "ca_state": "enum",
    "retransmits": "count",
    "probes": "count",
    "backoff": "count",
    "options": "flags",
    "wscale": "flags",
    "app_limited": "flags",
    "rto": "us",
    "ato": "us",
    "snd_mss": "bytes",
    "rcv_mss": "bytes",
    "unacked": "segments",
    "sacked": "segments",
    "lost": "segments",
    "retrans": "segments",
    "fackets": "segments",
    "last_data_sent": "ms",
    "last_ack_sent": "ms",
    "last_data_recv": "ms",
    "last_ack_recv": "ms",
    "pmtu": "bytes",
    "rcv_ssthresh": "bytes",
    "rtt": "us",
    "rttvar": "us",
    "snd_ssthresh": "segments",
    "snd_cwnd": "segments",
    "advmss": "bytes",
    "reordering": "segments",
    "rcv_rtt": "us",
    "rcv_space": "bytes",
    "total_retrans": "segments",
    "pacing_rate": "bytes/s",
    "max_pacing_rate": "bytes/s",
    "bytes_acked": "bytes",
    "bytes_received": "bytes",
    "segs_out": "segments",
    "segs_in": "segments",
    "notsent_bytes": "bytes",
    "min_rtt": "us",
    "data_segs_in": "segments",
    "data_segs_out": "segments",
    "delivery_rate": "bytes/s",
    "busy_time": "us",
    "rwnd_limited": "us",
    "sndbuf_limited": "us",
    "delivered": "segments",
    "delivered_ce": "segments",
    "bytes_sent": "bytes",
    "bytes_retrans": "bytes",
    "dsack_dups": "count",
    "reord_seen": "count",
    "rcv_ooopack": "count",
    "snd_wnd": "bytes",
    "rcv_wnd": "bytes",
    "rehash": "count",
    "total_rto": "count",
    "total_rto_recoveries": "count",
    "total_rto_time": "ms",
}

TCP_INFO_FORMAT = "=" + "".join(fmt for _, fmt in TCP_INFO_FIELDS)
STRUCT_SIZE = struct.calcsize(TCP_INFO_FORMAT)

# Ask for more than the struct we know about so a newer kernel never silently truncates.
REQUEST_SIZE = 2 * STRUCT_SIZE

TCP_CONGESTION_NAME_SIZE = 16

type TcpInfo = dict[str, int | None]


def build_layout() -> tuple[tuple[str, str, int], ...]:
    layout: list[tuple[str, str, int]] = []
    offset = 0

    for name, fmt in TCP_INFO_FIELDS:
        layout.append((name, fmt, offset))
        offset += struct.calcsize(fmt)

    return tuple(layout)


TCP_INFO_LAYOUT = build_layout()

assert STRUCT_SIZE == 248, f"unexpected tcp_info size: {STRUCT_SIZE}"
assert set(TCP_INFO_UNITS) == {name for name, _ in TCP_INFO_FIELDS}, "units table out of sync"


def parse_tcp_info(data: bytes) -> TcpInfo:
    info: TcpInfo = {}

    for name, fmt, offset in TCP_INFO_LAYOUT:
        end = offset + struct.calcsize(fmt)
        info[name] = struct.unpack_from(fmt, data, offset)[0] if end <= len(data) else None

    return info


def get_tcp_info_bytes(sock: socket.socket) -> bytes:
    return sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, REQUEST_SIZE)


def get_tcp_info(sock: socket.socket) -> TcpInfo:
    return parse_tcp_info(get_tcp_info_bytes(sock))


def get_tcp_algorithm(sock: socket.socket) -> str:
    name = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_CONGESTION, TCP_CONGESTION_NAME_SIZE)
    return name.split(b"\x00", 1)[0].decode("ascii")


def field_delta(curr: TcpInfo, prev: TcpInfo, name: str) -> int | None:
    after, before = curr[name], prev[name]
    return None if after is None or before is None else after - before
