# HalBot

HalBot is an API-only HalCode agent for a Debian guest VM. It calls provider APIs such as Grok, DeepSeek, Anthropic, and the other backends under `providers/`, but it does not host a model locally.

All code in this repository is MIT-licensed. See [LICENSE](LICENSE).

## Overview

HalBot combines:

- the agent runtime and tools (`HalCode9000.ailang`, `cc_tools/`, `IPCDispatch.ailang`)
- a web UI in `halbot-web/` for entering provider keys and chatting through the guest
- guest VM setup and automation in `vm/`
- desktop build notes and design docs in `docs/`

The project is designed to run as a guest VM on the host, with the browser and host tooling staying outside the model runtime.

## Prerequisites

Before running the project, make sure you have:

- `ailang.x` available on your `PATH`
- git
- a working QEMU-based VM setup for the Debian guest
- one or more provider API keys for the service(s) you want to use

The install flow expects [`ailang.x`](https://github.com/AiLang-Author/Ailang-Self-Hosting-) to be installed and available on `PATH`.

## Quick start

```bash
git clone https://github.com/AiLang-Author/HalBot.git
cd HalBot
./install.sh
```

`install.sh` does the setup work for the guest:

- downloads the Debian 13 genericcloud image
- creates a guest SSH key
- boots the VM
- installs the guest toolchain
- builds the agent and tools

## Run the page

```bash
chmod +x halbot-web/run-page.sh
./halbot-web/run-page.sh
```

Then open:

```text
http://127.0.0.1:8090/
```

The page connects to the guest over SSH using `vm/keys/id_ed25519`. If your VM lives somewhere else, set `HALBOT_VM_DIR` before starting the page.

Provider keys entered in the page are written to guest files such as:

- `~/.halcode/xai_key`
- `~/.halcode/deepseek_key`
- `~/.halcode/anthropic_key`

These keys are written on the guest and are not stored in this repository.

## Drive the bot from an assistant

`halbot-mcp/server.py` is a local MCP server. `halbot_task` sends one task to the guest and returns the reply. `halbot_health` checks the page. The server talks only to the page (default `http://127.0.0.1:8090`). The page adds the serve token. This server never reads it.

The bot's shell runs in the guest. That includes sudo and rm while the guest opt-in file exists. Start the page before calling the tool. A call blocks until the turn ends. The guest handles one turn at a time, so a task must not call this same HTTP port.

Opening this repo loads `.mcp.json` for Claude, and `.grok/config.toml` for Grok once the folder is trusted. Both run `halbot-mcp/run-mcp.sh`. To use the bot from other projects, register the absolute path once:

```bash
grok mcp add halbot -- /absolute/path/to/HalBot/halbot-mcp/run-mcp.sh
claude mcp add --scope user halbot -- /absolute/path/to/HalBot/halbot-mcp/run-mcp.sh
```

`HALBOT_PAGE` overrides the page URL. `HALBOT_MCP_TIMEOUT` is a request timeout in seconds. Leave it unset and the call waits until the turn finishes. A new server process starts a new chat. Later calls from that process continue the session unless `new_session` is true.

Grok's own MCP tool timeout is separate from the guest. The default is 6000 seconds. Raise `tool_timeout_sec` under `[mcp_servers.halbot]` for a longer guest task.

## Repository layout

- `HalCode9000.ailang` — main agent runtime
- `cc_tools/` — tool implementations and utility code
- `IPCDispatch.ailang` — IPC dispatch layer
- `halbot-web/` — chat page and local proxy layer
- `halbot-mcp/` — MCP server that sends one task to the guest and returns the reply
- `vm/` — guest VM provisioning and lifecycle scripts
- `docs/` — design and build notes
- `scripts/` — helper scripts, including desktop install helpers

## Guest VM notes

See [`vm/README.md`](vm/README.md) for the guest setup details.

The guest environment is a headless Debian 13 genericcloud VM. SSH and the bot API stay on the host loopback. The install flow creates the disk image, seed image, and SSH keys locally; these are not tracked in git.

`run.sh` forwards `127.0.0.1:2222` to the guest SSH port, and `127.0.0.1:8080` to the guest port 8080. `stop.sh` asks the guest to power off.

## Desktop / GTK notes

If you also want the GTK desk binary, use:

```bash
./scripts/install-desk.sh
```

The personal desk tree is [HalCodeGTK](https://github.com/AiLang-Author/HalCodeGTK).

Additional notes:

- desk build notes: [`docs/gtk-desk.md`](docs/gtk-desk.md)
- architecture and design: [`docs/halbot-spec.md`](docs/halbot-spec.md)

## Guest sudo policy

On the guest, `install.sh` creates `~/.halcode/allow_sudo`.

While that file exists, Bash allows a restricted set of privileged operations, including `sudo`, `rm`, `mv`, `dd`, `kill`, `crontab`, pipes into a shell, and redirects onto system paths.

This is intentional for the guest automation workflow, but it is a security boundary. Treat it as a privileged execution model rather than a general-purpose sandbox.

## Drive the bot from an assistant

`halbot-mcp/server.py` is a local MCP server. `halbot_task` sends one task to the guest and returns the reply. `halbot_health` checks the page. The server talks only to the page (default `http://127.0.0.1:8090`). The page adds the serve token. This server never reads it.

The bot's shell, including sudo and rm when the guest opt-in file exists, runs in the guest. Start the page before calling the tool. A call blocks until the turn ends. The guest handles one turn at a time, so a task must not call this same HTTP port.

Opening this repo loads `.mcp.json` for Claude, and `.grok/config.toml` for Grok once the folder is trusted. Both run `halbot-mcp/run-mcp.sh`. To use the bot from other projects, register the absolute path once:

```bash
grok mcp add halbot -- /absolute/path/to/HalBot/halbot-mcp/run-mcp.sh
claude mcp add --scope user halbot -- /absolute/path/to/HalBot/halbot-mcp/run-mcp.sh
```

`HALBOT_PAGE` overrides the page URL. `HALBOT_MCP_TIMEOUT` is a request timeout in seconds. Leave it unset and the call waits until the turn finishes. A new server process starts a new chat. Later calls from that process continue the session unless `new_session` is true.

Grok's own MCP tool timeout is separate from the guest. The default is 6000 seconds. Raise `tool_timeout_sec` under `[mcp_servers.halbot]` for a longer guest task.

## Build

```bash
./build.sh
```

For a full end-to-end setup that builds the agent and guest environment, use:

```bash
./install.sh
```

The guest runs the static binaries and does not need a compiler installed on the guest itself.

The agent loop has no tool-chain cap and no 5-minute wall clock. It keeps calling tools until the model stops or the turn fails.

`--serve` listens on `127.0.0.1`. The QEMU forwarding reaches the guest NIC, so the guest serve port is `8081` and `socat` on the guest bridges the host-to-guest traffic.

## Security and data handling

- Keys are entered in the browser UI.
- The browser does not store the serve token.
- Keys are written onto the guest filesystem.
- Provider secrets are not stored in this repository.

## Related projects

- [`Ailang-Self-Hosting`](https://github.com/AiLang-Author/Ailang-Self-Hosting-)
- [HalCodeGTK](https://github.com/AiLang-Author/HalCodeGTK)

## License

This project is released under the MIT License. See [LICENSE](LICENSE).
