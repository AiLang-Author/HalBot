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
import threading
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
_LOG_LEVEL = {"value": None}


def _poll_seconds():
    raw = os.environ.get("HALBOT_MCP_POLL", "").strip()
    if not raw:
        return 3.0
    try:
        value = float(raw)
    except ValueError:
        return 3.0
    if value < 2:
        return 2.0
    return value


POLL_SECONDS = _poll_seconds()

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
            "This call blocks until the turn ends. While it waits, progress "
            "notifications report the guest phase, and the result starts "
            "with that trace. A second call with the same server process "
            "continues the bot's session unless new_session is true. Do not "
            "call this server's own HTTP port from inside the task; the "
            "guest serve loop handles one turn at a time."
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
        "name": "halbot_activity",
        "description": (
            "Read-only snapshot of the HalBot guest. Reports whether a turn "
            "is running, which provider it is on, the latest phase, recent "
            "tool names, and a short reasoning tail. Does not start a task "
            "and does not interrupt one. Use this when another client may "
            "already be driving the bot."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "halbot_health",
        "description": "Check that the local HalBot page and guest are answering.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def http_request(method, path, payload=None, timeout=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if timeout is None:
        timeout = TIMEOUT
    req = urllib.request.Request(PAGE + path, data=data, headers=headers, method=method)
    try:
        resp = _OPENER.open(req, timeout=timeout)
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


def fetch_activity():
    try:
        body = http_request("GET", "/local/activity", timeout=8)
    except RuntimeError as exc:
        text = str(exc)
        if "HTTP 404" in text:
            text = (
                "This page does not serve /local/activity yet. "
                "Restart the page when no turn is running."
            )
        return {"ok": False, "error": text}
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {"ok": False, "error": "activity endpoint is not on this page yet"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "activity endpoint returned an unexpected body"}
    return data


def _clock(seconds):
    seconds = int(seconds or 0)
    return "%dm%02ds" % (seconds // 60, seconds % 60)


def activity_pulse(snap):
    if not isinstance(snap, dict):
        return ""
    if snap.get("ok") is False:
        return "activity unavailable: " + str(snap.get("error") or "unknown")[:160]
    if not snap.get("serve"):
        return "down"
    if not snap.get("busy"):
        return "idle"
    recent = snap.get("recent") if isinstance(snap.get("recent"), list) else []
    tools = snap.get("tools") if isinstance(snap.get("tools"), list) else []
    last = recent[-1] if recent else snap.get("phase") or "working"
    tool = tools[-1] if tools else ""
    return "%s %s — %s — %s — log %s" % (
        _clock(snap.get("elapsed_sec")),
        snap.get("phase") or "working",
        last,
        tool,
        snap.get("log_bytes"),
    )


def format_activity(snap):
    if not isinstance(snap, dict):
        return "status: unknown"
    if snap.get("ok") is False and snap.get("error"):
        return "status: unavailable\n" + str(snap.get("error"))
    if not snap.get("serve"):
        return "status: down\nNo HalCode9000 serve process is running."
    if not snap.get("busy"):
        return "status: idle\nThe guest is up. No agent turn is running."
    lines = [
        "status: live",
        "spec: %s" % (snap.get("spec") or "unknown"),
        "elapsed: %s" % _clock(snap.get("elapsed_sec")),
        "phase: %s" % (snap.get("phase") or "working"),
    ]
    recent = snap.get("recent") if isinstance(snap.get("recent"), list) else []
    if recent:
        lines.append("recent:")
        for item in recent[-8:]:
            if isinstance(item, str) and item:
                lines.append("- " + item[:180])
    tools = snap.get("tools") if isinstance(snap.get("tools"), list) else []
    if tools:
        lines.append("latest tools:")
        for item in tools[-6:]:
            if isinstance(item, str) and item:
                lines.append("- " + item[:140])
    think = snap.get("think_tail") if isinstance(snap.get("think_tail"), str) else ""
    age = snap.get("think_age_sec")
    if think and isinstance(age, int) and age < 180:
        lines.append("reasoning (%ds ago): %s" % (age, think))
    return "\n".join(lines)


def note_progress(token, count, message):
    text = message[:240]
    if token is not None:
        write_message({
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {"progressToken": token, "progress": count, "message": text},
        })
        return
    if _LOG_LEVEL["value"]:
        write_message({
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {"level": "info", "logger": "halbot", "data": text},
        })


def progress_token(msg):
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    if "progressToken" not in meta and isinstance(msg.get("_meta"), dict):
        meta = msg["_meta"]
    token = meta.get("progressToken") if isinstance(meta, dict) else None
    if isinstance(token, (str, int)) and not isinstance(token, bool):
        return token
    return None


def watch_turn(path, payload, token):
    box = {"body": None, "error": None}

    def worker():
        try:
            box["body"] = http_request("POST", path, payload)
        except Exception as exc:
            box["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    trace = []
    last = None
    count = 0
    snap = None
    while thread.is_alive():
        thread.join(POLL_SECONDS)
        if not thread.is_alive():
            break
        snap = fetch_activity()
        pulse = activity_pulse(snap)
        if not pulse or pulse == last:
            continue
        last = pulse
        count += 1
        if len(trace) == 20:
            del trace[0]
        trace.append(pulse)
        note_progress(token, count, pulse)
    thread.join()
    return box, trace, snap


def run_task(args, token=None):
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
    box, trace, snap = watch_turn(path, payload, token)
    if box["error"] is not None:
        return tool_text(str(box["error"]), True)
    body = box["body"] if isinstance(box["body"], str) else ""

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
    if trace:
        lines.append("live trace:")
        for pulse in trace:
            lines.append("- " + pulse)
        think = snap.get("think_tail") if isinstance(snap, dict) else ""
        age = snap.get("think_age_sec") if isinstance(snap, dict) else None
        if isinstance(think, str) and think and isinstance(age, int) and age < 180:
            lines.append("reasoning (%ds ago): %s" % (age, think))
        lines.append("")
    if got_session:
        lines.append("session_id: " + got_session)
    if model_name:
        lines.append("model: " + model_name)
    if stop:
        lines.append("stop_reason: " + stop)
    lines.append("")
    lines.append("".join(text_parts))
    return tool_text("\n".join(lines))


def run_activity():
    return tool_text(format_activity(fetch_activity()))


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
            "capabilities": {"tools": {}, "logging": {}},
            "serverInfo": {"name": "halbot", "version": "1.0.0"},
            "instructions": (
                "halbot_task sends one task to the HalBot guest and blocks "
                "until that turn finishes. Progress notifications, and the "
                "live trace at the top of the result, show the guest phase "
                "while it runs. halbot_activity reads that same snapshot "
                "without starting or interrupting a turn. Destructive shell "
                "commands run on the guest, not on the machine that launched "
                "this server. The guest serve loop handles one turn at a "
                "time. Do not ask the bot to call this server's HTTP port "
                "from inside the task."
            ),
        })
        return
    if method == "ping":
        reply(msg_id, {})
        return
    if method == "logging/setLevel":
        params = msg.get("params") or {}
        level = params.get("level")
        if isinstance(level, str) and level:
            _LOG_LEVEL["value"] = level
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
            reply(msg_id, run_task(args, progress_token(msg)))
        elif name == "halbot_activity":
            reply(msg_id, run_activity())
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
