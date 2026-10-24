# HalBot guest

Headless Debian 13 genericcloud VM. SSH and the bot API stay on the host loopback.

Run `./install.sh` from the repo root. It downloads the image, makes an SSH key, builds the seed, boots QEMU, and installs the guest.

`run.sh` forwards `127.0.0.1:2222` to guest ssh and `127.0.0.1:8080` to guest port 8080. `stop.sh` asks the guest to power off.

The disk, the base image, `seed.img`, and `keys/` are created on install and are not in git. The private SSH key stays on the machine that runs QEMU. `seed/user-data` has an `SSH_PUBLIC_KEY` placeholder. `make-seed.sh` fills it from `keys/id_ed25519.pub` when it builds `seed.img`.

Use the genericcloud image. The nocloud image has no cloud-init and stops in systemd-firstboot.

Copyright (c) 2026 Sean Collins, 2 Paws Machine and Engineering. MIT.
