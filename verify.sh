#!/bin/sh
set -eu

cd "$(dirname "$0")"

if ! make -q loader build/test_accounting build/test_window build/test_recovery; then
    echo "Build first: make all test" >&2
    exit 1
fi

if grep -qw a3_cc /proc/sys/net/ipv4/tcp_available_congestion_control; then
    echo "a3_cc is already registered; stop its existing loader before verifying." >&2
    exit 1
fi

original_algorithm=$(cat /proc/sys/net/ipv4/tcp_congestion_control)

./build/test_accounting
./build/test_window
./build/test_recovery

echo "Checking repeated registration, unconnected-socket readback, and removal..."
./loader --check
./loader --check

for signal in INT TERM; do
    echo "Checking cleanup after SIG$signal..."
    timeout --preserve-status --signal="$signal" --kill-after=5s 2s ./loader
done

if [ "$(cat /proc/sys/net/ipv4/tcp_congestion_control)" != "$original_algorithm" ]; then
    echo "The default congestion algorithm changed during verification." >&2
    exit 1
fi

echo "Local verification passed; the default algorithm is unchanged. No servers contacted."
