#!/usr/bin/env bash
# Rerun every host test of the node code and save one log per subsystem.
#
#   node/testing/run_host_tests.sh
#
# Needs only a host C compiler (cc) and python3: no Pico, no Arm toolchain.
# These tests compile the real sources from node/app_program/ for the PC, so
# they check logic and arithmetic, not timing or hardware. Each log is named
# <date>_host_<commit>.txt and starts with the commit, machine and compiler.
# Commit your work first, so the commit in the log is the code that was run.
# Exit status is 0 only if every command passed.

set -u
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root" || exit 1

day=$(date +%Y-%m-%d)
commit=$(git rev-parse --short HEAD)
if git status --porcelain --untracked-files=no | grep -q .; then
    tree="$commit + uncommitted changes"
else
    tree="$commit (tracked files clean)"
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
failed=0

header() {
    echo "$1"
    echo "Date: $(date '+%Y-%m-%d %H:%M %z')"
    echo "Commit: $tree"
    echo "Machine: $(uname -sm)"
    echo "Compiler: $(cc --version | head -1)"
    echo "Python: $(python3 --version 2>&1)"
    echo
}

# Print a command, run it, and record whether it passed.
run() {
    echo "\$ $*"
    "$@"
    local code=$?
    echo "exit: $code"
    echo
    [ "$code" -eq 0 ] || failed=1
}

log() { echo "node/testing/$1/logs/${day}_host_${commit}.txt"; }

s1=node/app_program/subsystem1
s2=node/app_program/subsystem2
s3=node/app_program/subsystem3
s5=node/app_program/subsystem5
h3=node/testing/subsystem3/host
strict="-std=c11 -Wall -Wextra -Werror"

# ---- Subsystems 1 and 2: DSP and classifier replay against the reference
{
    header "S1/S2 host replay (S1-U04, S2-U03, S2-U04, S2-U05). Host only."
    run python3 node/testing/subsystem1/test_audio_port.py
} > "$(log subsystem1)" 2>&1

# ---- Subsystem 2: speech gate and persistence
{
    header "S2 speech gate (S2-U07). Host only."
    run cc $strict node/testing/subsystem2/speech_gate_check.c \
        $s2/audio_inference.c $s2/classifier_timing.c -o "$tmp/speech-gate"
    run "$tmp/speech-gate"
} > "$(log subsystem2)" 2>&1

# ---- Subsystem 3: decoding, CO2 protocol, service, drivers, start-up
{
    header "S3 host suite. Host only: register and SDK calls are test doubles."
    inc="-I $s3 -I $s5"
    service="$s3/environment.c $s3/acd1100_protocol.c $s3/drv_acd1100.c $s3/drv_dht22.c
             $s3/s3_telemetry.c $s3/environment_service.c $s3/task_environment.c"

    run cc $strict $inc $s3/environment.c $h3/environment_host_test.c -o "$tmp/t"
    run "$tmp/t"
    run cc $strict $inc $s3/environment.c $s3/acd1100_protocol.c $h3/acd1100_host_test.c -o "$tmp/t"
    run "$tmp/t"
    run cc $strict $inc $s3/environment.c $s3/s3_telemetry.c $s5/s5_protocol.c \
        $h3/s5_environment_host_test.c -o "$tmp/t"
    run "$tmp/t"
    run cc $strict $inc -include $h3/utk_mock.h $service $h3/service_host_test.c -o "$tmp/t"
    run "$tmp/t"
    run cc $strict $inc -DAPP_TEST=1 -include $h3/utk_mock.h $service $h3/service_host_test.c -o "$tmp/t"
    run "$tmp/t"
    run cc $strict -DAPP_TEST=1 -I $h3 $inc $h3/observer_host_test.c -o "$tmp/t"
    run "$tmp/t"
    run cc $strict -include $h3/utk_mock.h -I $h3/registers -I $s3 $s3/drv_uart1.c \
        $h3/uart_register_host_test.c -o "$tmp/t"
    run "$tmp/t"
    run cc $strict -include $h3/startup_mock.h -I $s3 $s3/subsystem3.c $h3/startup_host_test.c -o "$tmp/t"
    for scenario in success consumer-create consumer-start environment-create environment-start; do
        run "$tmp/t" "$scenario"
    done
    run cc -std=gnu11 -Wall -Wextra -Werror -DTM_WIFI_CYW43=1 -I $h3/sdk_mock -I $s3 \
        $s3/drv_dht22_hw.c $h3/dht_hw_host_test.c -o "$tmp/t"
    run "$tmp/t"
} > "$(log subsystem3)" 2>&1

# ---- Subsystem 5: protocol state, then the PC decodes what the C code built
{
    header "S5 host run (S5-U01..U11 plus edge cases), then all PC unit tests. Host only."
    run cc $strict -I $s5 node/testing/subsystem5/host/s5_protocol_host_test.c \
        $s5/s5_protocol.c -o "$tmp/s5host"
    echo "\$ s5host | xxd   (the asserts run first; the bytes are the packets it built)"
    "$tmp/s5host" > "$tmp/s5.bin"
    code=$?
    xxd "$tmp/s5.bin"
    echo "exit: $code"
    echo
    [ "$code" -eq 0 ] || failed=1
    echo "\$ (cd pc && python3 -m unittest -v)"
    (cd pc && python3 -m unittest -v)
    code=$?
    echo "exit: $code"
    [ "$code" -eq 0 ] || failed=1
} > "$(log subsystem5)" 2>&1

for name in subsystem1 subsystem2 subsystem3 subsystem5; do
    file=$(log "$name")
    if grep -q '^exit: [^0]' "$file"; then
        echo "FAIL  $file"
    else
        echo "PASS  $file"
    fi
done
exit "$failed"
