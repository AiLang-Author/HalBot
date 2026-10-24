#!/bin/bash
# Build the NoCloud cidata seed from seed/user-data, meta-data, and network-config.
set -euo pipefail
cd "$(dirname "$0")"
rm -f seed.img
truncate -s 8M seed.img
mkfs.vfat -n cidata seed.img >/dev/null
mcopy -i seed.img seed/user-data seed/meta-data seed/network-config ::
echo "wrote $PWD/seed.img"
