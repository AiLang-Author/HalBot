#!/bin/bash
# Build the NoCloud cidata seed. SSH_PUBLIC_KEY in seed/user-data is
# replaced from keys/id_ed25519.pub. The template in git stays generic.
# Copyright (c) 2026 Sean Collins, 2 Paws Machine and Engineering. MIT.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f keys/id_ed25519.pub ]]; then
    echo "missing keys/id_ed25519.pub — run ./install.sh from the repo root" >&2
    exit 1
fi

python3 - << 'PY'
from pathlib import Path
pub = Path("keys/id_ed25519.pub").read_text().strip()
text = Path("seed/user-data").read_text()
if "SSH_PUBLIC_KEY" in text:
    text = text.replace("SSH_PUBLIC_KEY", pub)
out = Path("/tmp/halbot-user-data")
out.write_text(text)
PY

rm -f seed.img
truncate -s 8M seed.img
mkfs.vfat -n cidata seed.img >/dev/null
mcopy -i seed.img /tmp/halbot-user-data ::user-data
mcopy -i seed.img seed/meta-data seed/network-config ::
rm -f /tmp/halbot-user-data
echo "wrote $PWD/seed.img"
