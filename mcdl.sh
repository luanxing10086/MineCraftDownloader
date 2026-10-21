#!/usr/bin/env sh
# mcdl 的 Unix 启动器
set -e
cd "$(dirname "$0")"
exec python3 -m mcdl "$@"
