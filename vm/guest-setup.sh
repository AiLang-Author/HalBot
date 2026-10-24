#!/bin/bash
# Runs on the Debian guest as the halbot user. Installs the toolchain,
# Postgres, and starts the bot. This machine is the bot's own machine.
# Copyright (c) 2026 Sean Collins, 2 Paws Machine and Engineering. MIT.
set -euo pipefail

sudo -n true

if ! swapon --show | grep -q .; then
    sudo -n dd if=/dev/zero of=/swapfile bs=1M count=1024 status=none
    sudo -n chmod 600 /swapfile
    sudo -n mkswap /swapfile
    sudo -n swapon /swapfile
    if ! grep -q '/swapfile' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' | sudo -n tee -a /etc/fstab >/dev/null
    fi
fi

export DEBIAN_FRONTEND=noninteractive
sudo -n apt-get update
sudo -n apt-get install -y \
    git build-essential clang make cmake pkg-config \
    jq unzip zip socat postgresql \
    python3-pip python3-venv python3-dev \
    nodejs npm golang-go rustc cargo lua5.4 \
    universal-ctags openjdk-21-jdk-headless

if ! sudo -n -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='halbot'" | grep -q 1; then
    sudo -n -u postgres createuser halbot
fi
if ! sudo -n -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='ailang_system'" | grep -q 1; then
    sudo -n -u postgres createdb -O halbot ailang_system
fi

mkdir -p "$HOME/.halcode"
: > "$HOME/.halcode/allow_sudo"
if [[ ! -f "$HOME/.halcode/system_prompt.txt" && -f "$HOME/HalBot/config/system_prompt.txt" ]]; then
    cp "$HOME/HalBot/config/system_prompt.txt" "$HOME/.halcode/system_prompt.txt"
fi

if [[ ! -x "$HOME/HalBot/HalCode9000.x" ]]; then
    echo "no $HOME/HalBot/HalCode9000.x — build on the host with ailang.x, then re-run install.sh"
    exit 0
fi

cd "$HOME/HalBot"
if ! curl -fsS -m 2 http://127.0.0.1:8081/healthz >/dev/null 2>&1; then
    nohup ./HalCode9000.x --serve --port 8081 >> "$HOME/halcode-serve.log" 2>&1 &
    echo $! > "$HOME/halcode-serve.pid"
fi
if ! ss -ltn | grep -q ':8080 '; then
    nohup socat TCP-LISTEN:8080,bind=0.0.0.0,fork,reuseaddr TCP:127.0.0.1:8081 \
        >> "$HOME/halcode-socat.log" 2>&1 &
    echo $! > "$HOME/halcode-socat.pid"
fi

ok=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if curl -fsS -m 2 http://127.0.0.1:8081/healthz >/dev/null 2>&1; then
        ok=1
        break
    fi
    sleep 0.5
done
if [[ "$ok" -ne 1 ]]; then
    echo "serve did not answer on 127.0.0.1:8081"
    exit 1
fi
echo "guest ready"
