# HalBot

API-only HalCode agent for a Debian guest. The bot calls a provider API (Grok, DeepSeek, Anthropic, and the other backends in `providers/`). It does not host a model.

All of the code in this repository is MIT. See [LICENSE](LICENSE).

```bash
git clone https://github.com/AiLang-Author/HalBot.git
cd HalBot
./install.sh
```

`install.sh` needs [`ailang.x`](https://github.com/AiLang-Author/Ailang-Self-Hosting-) on `PATH`. It downloads Debian 13 genericcloud, creates a guest SSH key, boots the VM, installs the guest toolchain and Postgres, and starts the bot. Then:

```bash
./halbot-web/run-page.sh
```

Open http://127.0.0.1:8090/ and enter provider keys in the page. Keys are written on the guest. They are not stored in this repo.

The GTK desk installer, if you want that binary too, is `scripts/install-desk.sh`. The personal desk tree is [HalCodeGTK](https://github.com/AiLang-Author/HalCodeGTK).

## What is here

- Agent, serve mode, and tools (`HalCode9000.ailang`, `cc_tools/`, `IPCDispatch.ailang`). Pgmem and Relmem sources are included.
- Chat page in `halbot-web/`. It binds `127.0.0.1:8090`, proxies `/healthz` and `/v1/*` to the guest, and writes provider keys onto the guest. The browser does not store the serve token.
- Guest VM scripts in `vm/`. See `vm/README.md`.
- Desk build notes carried from the fork: `docs/gtk-desk.md`.
- Design: `docs/halbot-spec.md`.

## Guest sudo

On the guest, `install.sh` creates `~/.halcode/allow_sudo`. While that file exists, Bash allows `sudo`, `rm`, `mv`, `dd`, `kill`, `crontab`, pipes into a shell, and redirects onto system paths. That is this bot's own machine. A checkout without that file keeps every one of those blocks.

The agent loop has no tool-chain cap and no 5-minute wall clock. It keeps calling tools until the model stops or a turn fails. The personal HalCode desk is a separate tree and still has its own pause.

## Run the page

```bash
chmod +x halbot-web/run-page.sh
./halbot-web/run-page.sh
```

The page SSHes to the guest with `vm/keys/id_ed25519`. Set `HALBOT_VM_DIR` if the VM lives somewhere else. Keys posted in the page go to the guest files `~/.halcode/xai_key`, `deepseek_key`, and `anthropic_key`.

## Build

`ailang.x` on `PATH`. `./build.sh` compiles the agent and tools. `./install.sh` does that and then builds the guest. `--self-update` restarts a running desk; do not use it against a personal HalCodeGTK checkout.

The guest runs the static binaries. It does not need the compiler. `--serve` listens on `127.0.0.1`. The QEMU forward reaches the guest NIC, so the guest serve port is `8081` and `socat` on the guest forwards `0.0.0.0:8080` to `127.0.0.1:8081`.
