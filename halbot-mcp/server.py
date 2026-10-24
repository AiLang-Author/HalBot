#!/usr/bin/env python3
"""MCP server that drives a local HalBot.

One tool sends a task to the guest bot and returns its reply. The bot's
shell, including destructive commands, runs in the guest. This process
does not run those commands on the machine that launched it.

Talks to the chat page at HALBOT_PAGE (default http://127.0.0.1:8090).
The page adds the guest serve token. This server never reads that token.

Stdio transport is newline-delimited JSON-RPC, the same framing as
HalCode9000.x --mcp. Logs go to stderr.

Copyright (c) 2026 Sean Collins, 2 Paws Machine and Engineering. MIT.
"""
import json
import os
import sys
import urllib.error
import urllib.request

PAGE = os.environ.get("HALBOT_PAGE", "http://127.0.0.1:8090").rstrip("/")


def _request_timeout():
    raw = os.environ.get("HALBOT_MCP_TIMEOUT", "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


TIMEOUT = _request_timeout()

# Local page. Ignore http_proxy so a machine-wide proxy cannot swallow it.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# One remembered session per server process. A new process starts a new chat.
_SESSION = {"id": None}

_MAX_FRAME = 8_000_000


def log(msg):
    sys.stderr.write("halbot-mcp: %s\n" % msg)
    sys.stderr.flush()


def write_message(obj):
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8") + b"\n"
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def read_message():
    while True:
        line = sys.stdin.buffer.readline()
        if line == b"":
            return None
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
            if length < 0 or length > _MAX_FRAME:
                raise ValueError("content-length out of range")
            while True:
                hdr = sys.stdin.buffer.readline()
                if hdr in (b"\r\n", b"\n", b""):
                    break
            body = sys.stdin.buffer.read(length)
            if len(body) != length:
                raise ValueError("short content-length body")
            return json.loads(body.decode("utf-8"))
        return json.loads(line.decode("utf-8"))


def reply(msg_id, result):
    write_message({"jsonrpc": "2.0", "id": msg_id, "result": result})


def reply_error(msg_id, code, message):
    write_message({
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    })


def tool_text(text, is_error=False):
    out = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["isError"] = True
    return out


TOOLS = [
    {
        "name": "halbot_task",
        "description": (
            "Send one task to the HalBot running in its guest VM and wait "
            "for the reply. The bot edits files, runs shells, and may use "
            "sudo, rm, and other destructive commands on that guest only. "
            "This call blocks until the turn ends. A second call with the "
            "same server process continues the bot's session unless "
            "new_session is true. Do not call this server's own HTTP port "
            "from inside the task; the guest serve loop handles one turn "
            "at a time."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The task or follow-up, as the user would type it.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Continue this HalBot session. Omit to reuse the last one from this process.",
                },
                "new_session": {
                    "type": "boolean",
                    "description": "Start a fresh HalBot session instead of continuing.",
                },
                "provider": {
                    "type": "string",
                    "description": "Provider alias: grok, deepseek, or anthropic. Omit for the guest default.",
                },
                "model": {
                    "type": "string",
                    "description": "Model id for that provider. Omit for the guest default.",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "halbot_health",
        "description": "Check that the local HalBot page and guest are answering.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def http_request(method, path, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(PAGE + path, data=data, headers=headers, method=method)
    try:
        resp = _OPENER.open(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError("HTTP %s %s" % (exc.code, body[:500]))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "HalBot page is not answering at %s (%s). Start it with ./halbot-web/run-page.sh"
            % (PAGE, exc.reason)
        )
    return resp.read().decode("utf-8", "replace")


def parse_sse(body):
    event = "message"
    data_lines = []
    found = []

    def flush():
        nonlocal event, data_lines
        if not data_lines:
            event = "message"
            return
        raw = "\n".join(data_lines)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        found.append((event, payload))
        event = "message"
        data_lines = []

    for line in body.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line == "":
            flush()
    flush()
    return found


def clean_session_id(value):
    """Return a safe id, None when absent, or '' when the value is unusable."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value == "":
        return None
    if len(value) > 80:
        return ""
    for ch in value:
        letter = ("a" <= ch <= "z") or ("A" <= ch <= "Z")
        digit = "0" <= ch <= "9"
        if not (letter or digit or ch in "-_"):
            return ""
    return value


def run_task(args):
    message = args.get("message") if isinstance(args, dict) else None
    if not isinstance(message, str) or message.strip() == "":
        return tool_text("missing message", True)
    payload = {"message": message}
    provider = args.get("provider") if isinstance(args, dict) else None
    model = args.get("model") if isinstance(args, dict) else None
    if isinstance(provider, str) and provider.strip():
        payload["provider"] = provider.strip()
    if isinstance(model, str) and model.strip():
        payload["model"] = model.strip()

    new_session = bool(args.get("new_session")) if isinstance(args, dict) else False
    supplied = clean_session_id(args.get("session_id") if isinstance(args, dict) else None)
    if supplied == "":
        return tool_text("session_id must be letters, digits, hyphen, or underscore", True)
    if new_session:
        session_id = None
    elif supplied is not None:
        session_id = supplied
    else:
        session_id = _SESSION["id"]

    if session_id:
        path = "/v1/sessions/%s/messages" % session_id
    else:
        path = "/v1/chat"
    try:
        body = http_request("POST", path, payload)
    except RuntimeError as exc:
        return tool_text(str(exc), True)

    text_parts = []
    got_session = session_id or ""
    model_name = ""
    stop = ""
    for name, data in parse_sse(body):
        if not isinstance(data, dict):
            continue
        if name == "session":
            got_session = data.get("session_id") or got_session
            model_name = data.get("model") or model_name
        elif name == "text_delta":
            piece = data.get("text")
            if isinstance(piece, str):
                text_parts.append(piece)
        elif name == "turn_done":
            stop = data.get("stop_reason") or stop
    safe_session = clean_session_id(got_session if isinstance(got_session, str) else None)
    if safe_session:
        _SESSION["id"] = safe_session
        got_session = safe_session
    else:
        got_session = ""
    if not text_parts and not got_session:
        return tool_text("HalBot returned no SSE events:\n" + body[:800], True)
    lines = []
    if got_session:
        lines.append("session_id: " + got_session)
    if model_name:
        lines.append("model: " + model_name)
    if stop:
        lines.append("stop_reason: " + stop)
    lines.append("")
    lines.append("".join(text_parts))
    return tool_text("\n".join(lines))


def run_health():
    try:
        body = http_request("GET", "/healthz")
    except RuntimeError as exc:
        return tool_text(str(exc), True)
    return tool_text(body.strip() or "ok")


def handle(msg):
    method = msg.get("method", "")
    msg_id = msg.get("id", None)
    if msg_id is None or method.startswith("notifications/"):
        return
    if method == "initialize":
        params = msg.get("params") or {}
        version = params.get("protocolVersion") or "2024-11-05"
        reply(msg_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "halbot", "version": "1.0.0"},
            "instructions": (
                "halbot_task sends one task to the HalBot guest and blocks "
                "until that turn finishes. Destructive shell commands run on "
                "the guest, not on the machine that launched this server. "
                "The guest serve loop handles one turn at a time. Do not ask "
                "the bot to call this server's HTTP port from inside the task."
            ),
        })
        return
    if method == "ping":
        reply(msg_id, {})
        return
    if method == "tools/list":
        reply(msg_id, {"tools": TOOLS})
        return
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "halbot_task":
            reply(msg_id, run_task(args))
        elif name == "halbot_health":
            reply(msg_id, run_health())
        else:
            reply_error(msg_id, -32602, "unknown tool: %s" % name)
        return
    if method in ("resources/list", "prompts/list"):
        key = "resources" if method.startswith("resources") else "prompts"
        reply(msg_id, {key: []})
        return
    reply_error(msg_id, -32601, "Method not found")


def main():
    log("ready, page %s" % PAGE)
    while True:
        try:
            msg = read_message()
        except (json.JSONDecodeError, ValueError, UnicodeError) as exc:
            log("bad message: %s" % exc)
            continue
        if msg is None:
            return
        if not isinstance(msg, dict):
            continue
        try:
            handle(msg)
        except Exception as exc:
            log("handler error: %s" % exc)
            msg_id = msg.get("id", None)
            if msg_id is not None:
                reply_error(msg_id, -32603, str(exc))


if __name__ == "__main__":
    main()
