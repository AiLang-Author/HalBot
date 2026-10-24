#!/bin/bash
# Chat window on 127.0.0.1:8090. The browser never sees the serve token.
set -euo pipefail
cd "$(dirname "$0")"
if [[ -z "${HALBOT_VM_DIR:-}" ]]; then
    if [[ ! -f ../vm/keys/id_ed25519 && -f /home/bob/halbot-vm/keys/id_ed25519 ]]; then
        export HALBOT_VM_DIR=/home/bob/halbot-vm
    fi
fi
exec /usr/bin/python3 ./serve.py
