#!/usr/bin/env bash
# HalBot install. All code in this repo is MIT.
# Copyright (c) 2026 Sean Collins, 2 Paws Machine and Engineering.
#
# From a fresh clone:
#   ./install.sh
#
# Options:
#   --no-build   skip ./build.sh (binaries already present)
#   --no-vm      build only, do not download or boot the guest
#   --no-guest   boot the guest, do not apt-install inside it
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM="$ROOT/vm"
BUILD=1
DO_VM=1
DO_GUEST=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-build) BUILD=0; shift ;;
        --no-vm) DO_VM=0; DO_GUEST=0; shift ;;
        --no-guest) DO_GUEST=0; shift ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

log() { printf '==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

if [[ "$BUILD" -eq 1 ]]; then
    if ! command -v ailang.x >/dev/null 2>&1; then
        die "ailang.x is not on PATH. Clone https://github.com/AiLang-Author/Ailang-Self-Hosting- and run ./install_compiler.sh, then re-run ./install.sh"
    fi
    log "Building agent and tools"
    (cd "$ROOT" && ./build.sh)
fi

if [[ "$DO_VM" -eq 0 ]]; then
    log "Build finished. Guest was not started."
    exit 0
fi

need=()
command -v qemu-system-x86_64 >/dev/null 2>&1 || need+=(qemu-system-x86)
command -v qemu-img >/dev/null 2>&1 || need+=(qemu-utils)
command -v mkfs.vfat >/dev/null 2>&1 || need+=(dosfstools)
command -v mcopy >/dev/null 2>&1 || need+=(mtools)
command -v ssh >/dev/null 2>&1 || need+=(openssh-client)
command -v ssh-keygen >/dev/null 2>&1 || need+=(openssh-client)
command -v python3 >/dev/null 2>&1 || need+=(python3)
command -v curl >/dev/null 2>&1 || need+=(curl)
command -v rsync >/dev/null 2>&1 || need+=(rsync)
if [[ ${#need[@]} -gt 0 ]]; then
    # de-dupe
    mapfile -t need < <(printf '%s\n' "${need[@]}" | awk '!seen[$0]++')
    if command -v apt-get >/dev/null 2>&1; then
        log "Installing host packages: ${need[*]}"
        sudo apt-get update
        sudo apt-get install -y "${need[@]}"
    else
        die "missing tools. Install: ${need[*]}"
    fi
fi

IMG="$VM/debian-13-genericcloud-amd64.qcow2"
URL="https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.qcow2"
if [[ ! -f "$IMG" ]]; then
    log "Downloading Debian 13 genericcloud"
    curl -fL --retry 3 -o "$IMG.partial" "$URL"
    mv "$IMG.partial" "$IMG"
fi
log "Checking Debian image checksum"
(
    cd "$VM"
    sha512sum -c SHA512SUMS --ignore-missing --status
) || die "SHA512 mismatch for $IMG. Delete it and re-run."

mkdir -p "$VM/keys"
chmod 700 "$VM/keys"
if [[ ! -f "$VM/keys/id_ed25519" ]]; then
    log "Creating an SSH key for this guest"
    ssh-keygen -t ed25519 -f "$VM/keys/id_ed25519" -N "" -C "halbot"
fi
chmod 600 "$VM/keys/id_ed25519"

log "Building cloud-init seed"
"$VM/make-seed.sh"

if [[ ! -f "$VM/disk.qcow2" ]]; then
    log "Creating a 16G guest disk"
    (
        cd "$VM"
        qemu-img create -f qcow2 -F qcow2 -b debian-13-genericcloud-amd64.qcow2 disk.qcow2 16G
    )
fi

port_busy() { ss -ltn | grep -q ":$1 "; }

if [[ -f "$VM/halbot.pid" ]] && kill -0 "$(cat "$VM/halbot.pid")" 2>/dev/null; then
    log "Guest already running, pid $(cat "$VM/halbot.pid")"
elif port_busy 2222 || port_busy 8080; then
    die "127.0.0.1:2222 or :8080 is already in use. Stop the other QEMU before starting this guest."
else
    log "Starting the guest"
    "$VM/run.sh"
fi

SSH=(ssh
    -i "$VM/keys/id_ed25519"
    -p 2222
    -o UserKnownHostsFile="$VM/keys/known_hosts"
    -o StrictHostKeyChecking=accept-new
    -o BatchMode=yes
    -o ConnectTimeout=5
    halbot@127.0.0.1
)

if [[ "$DO_GUEST" -eq 0 ]]; then
    log "Guest is up. SSH: ssh -i $VM/keys/id_ed25519 -p 2222 halbot@127.0.0.1"
    exit 0
fi

log "Waiting for SSH"
ready=0
for _ in $(seq 1 90); do
    if "${SSH[@]}" true >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 2
done
[[ "$ready" -eq 1 ]] || die "guest SSH did not come up on port 2222"

log "Copying the tree to the guest"
rsync -a \
    --exclude '.git' \
    --exclude 'vm' \
    --exclude '.claude' \
    --exclude '__pycache__' \
    -e "ssh -i $VM/keys/id_ed25519 -p 2222 -o UserKnownHostsFile=$VM/keys/known_hosts -o StrictHostKeyChecking=accept-new -o BatchMode=yes" \
    "$ROOT/" halbot@127.0.0.1:HalBot/

log "Installing guest packages and starting the bot"
"${SSH[@]}" 'bash -s' < "$VM/guest-setup.sh"

log "Done"
echo "    SSH:   ssh -i $VM/keys/id_ed25519 -p 2222 halbot@127.0.0.1"
echo "    Page:  $ROOT/halbot-web/run-page.sh"
echo "    Open:  http://127.0.0.1:8090/"
echo "    Keys go in the page. They are written on the guest, not in this repo."
