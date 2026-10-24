#!/bin/bash
# Headless Debian 13 guest for HalBot. API and SSH stay on the host loopback.
set -euo pipefail
cd "$(dirname "$0")"

if [[ -f halbot.pid ]] && kill -0 "$(cat halbot.pid)" 2>/dev/null; then
    echo "halbot already running, pid $(cat halbot.pid)"
    exit 0
fi

: > serial.log
qemu-system-x86_64 \
    -name halbot \
    -machine pc,accel=kvm \
    -cpu host \
    -m 2048 \
    -smp 2 \
    -display none \
    -daemonize \
    -pidfile "$PWD/halbot.pid" \
    -serial file:"$PWD/serial.log" \
    -qmp unix:"$PWD/qmp.sock",server,nowait \
    -drive file="$PWD/disk.qcow2",if=virtio,format=qcow2,discard=unmap \
    -drive file="$PWD/seed.img",if=virtio,format=raw,readonly=on \
    -nic user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:2222-:22,hostfwd=tcp:127.0.0.1:8080-:8080

echo "started pid $(cat halbot.pid)"
echo "ssh: ssh -i $PWD/keys/id_ed25519 -p 2222 halbot@127.0.0.1"
echo "api forward: 127.0.0.1:8080 -> guest:8080"
