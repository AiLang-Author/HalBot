# HalBot

API-only HalCode agent for a Debian guest. The bot calls a provider API (Grok, DeepSeek, Anthropic, and the other backends in `providers/`). It does not host a model.

This tree is the bot. The personal GTK desk stays in [HalCodeGTK](https://github.com/AiLang-Author/HalCodeGTK). Privilege changes for the guest belong here.

Copyright (c) 2026 Sean Collins, 2 Paws Machine and Engineering. MIT.

## What is here

- Agent, serve mode, and tools (`HalCode9000.ailang`, `cc_tools/`, `IPCDispatch.ailang`). Pgmem and Relmem sources are included.
- Chat page in `halbot-web/`. It binds `127.0.0.1:8090`, proxies `/healthz` and `/v1/*` to the guest, and writes provider keys onto the guest. The browser does not store the serve token.
- Guest VM scripts in `vm/`. See `vm/README.md`.
- Desk build notes carried from the fork: `docs/gtk-desk.md`.
- Design: `docs/halbot-spec.md`.

## Guest sudo

`cc_tools/cc_bash_ipc.ailang` allows `sudo`, `rm`, `mv`, `dd`, `kill`, `crontab`, pipes into a shell, and redirects onto system paths only when `~/.halcode/allow_sudo` exists on that machine. Create that empty file on the guest. Do not create it on a personal desk. A desk without the file keeps every one of those blocks.

The agent loop has no tool-chain cap and no 5-minute wall clock. It keeps calling tools until the model stops or a turn fails. The personal HalCode desk is a separate tree and still has its own pause.

## Run the page

```bash
chmod +x halbot-web/run-page.sh
./halbot-web/run-page.sh
```

The page SSHes to the guest with `vm/keys/id_ed25519` unless `HALBOT_VM_DIR` points somewhere else. Keys posted in the page go to the guest files `~/.halcode/xai_key`, `deepseek_key`, and `anthropic_key`.

## Build

`ailang.x` on `PATH`. `./build.sh` compiles the agent and tools. Build products (`*.x`) are gitignored. `--self-update` restarts a running desk; do not use it against a personal HalCodeGTK checkout.

The guest runs the static binaries. It does not need the compiler. `--serve` listens on `127.0.0.1`. The QEMU forward reaches the guest NIC, so the guest serve port is `8081` and `socat` on the guest forwards `0.0.0.0:8080` to `127.0.0.1:8081`.
