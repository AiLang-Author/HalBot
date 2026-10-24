#!/bin/bash
# Ask the guest to power off, then stop QEMU if it is still there.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f halbot.pid ]]; then
    echo "not running"
    exit 0
fi
pid=$(cat halbot.pid)
if ! kill -0 "$pid" 2>/dev/null; then
    rm -f halbot.pid qmp.sock
    echo "stale pid $pid"
    exit 0
fi

python3 - << 'PY'
import socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(3)
s.connect("qmp.sock")
s.recv(65536)
s.sendall(b'{"execute":"qmp_capabilities"}\n')
s.recv(65536)
s.sendall(b'{"execute":"system_powerdown"}\n')
s.recv(65536)
PY

for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
done
if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" || true
    sleep 1
fi
rm -f halbot.pid qmp.sock
echo "stopped"
