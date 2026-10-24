# HalBot guest

Headless Debian 13 genericcloud VM. SSH and the bot API stay on the host loopback.

The running disk, the base image, `seed.img`, and `keys/` are not in git. The disk holds the guest filesystem, including provider key files. The private SSH key stays on the machine that runs QEMU.

## Files

- `run.sh` starts QEMU. Forwards `127.0.0.1:2222` to guest ssh and `127.0.0.1:8080` to guest port 8080.
- `stop.sh` asks the guest to power off.
- `seed/` is the cloud-init source. `make-seed.sh` builds `seed.img` (needs `dosfstools` and `mtools`).
- `SHA512SUMS` is the Debian cloud image checksum list.

## New guest

```bash
# https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.qcow2
sha512sum -c SHA512SUMS --ignore-missing
qemu-img create -f qcow2 -F qcow2 -b debian-13-genericcloud-amd64.qcow2 disk.qcow2 16G
mkdir -p keys
ssh-keygen -t ed25519 -f keys/id_ed25519 -N ""
# Put that public key in seed/user-data, then:
./make-seed.sh
./run.sh
```

Use the genericcloud image. The nocloud image has no cloud-init and stops in systemd-firstboot.

On this machine the live guest is still `/home/bob/halbot-vm` because QEMU has that disk open. These scripts are the copy that belongs in the repo.
