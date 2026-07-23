#!/bin/sh
set -eu

real_compiler=$1
shift

if [ -n "${FIXTURE_WRAPPER_LOG:-}" ]; then
    printf '%s\n' "$real_compiler $*" >> "$FIXTURE_WRAPPER_LOG"
fi

exec "$real_compiler" "$@"
