"""Read-only guest snapshot. The page runs this on the guest over SSH.

It reports whether a turn is running. It does not signal, write, or
connect to the serve port.

Copyright (c) 2026 Sean Collins, 2 Paws Machine and Engineering. MIT.
"""
import json
import os
import time

CLOCK = os.sysconf("SC_CLK_TCK") or 100


def cmdline(pid):
    try:
        raw = open("/proc/%s/cmdline" % pid, "rb").read()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()


def stat_fields(pid):
    try:
        text = open("/proc/%s/stat" % pid).read()
    except OSError:
        return None
    cut = text.rfind(")")
    if cut < 0:
        return None
    return text[cut + 2 :].split()


def boot_time():
    try:
        lines = open("/proc/stat")
    except OSError:
        return 0
    for line in lines:
        if line.startswith("btime "):
            return int(line.split()[1])
    return 0


def elapsed_sec(pid, btime):
    fields = stat_fields(pid)
    if not fields or len(fields) < 20:
        return 0
    start = btime + (int(fields[19]) / float(CLOCK))
    return max(0, int(time.time() - start))


def ppid_of(pid):
    fields = stat_fields(pid)
    if not fields or len(fields) < 2:
        return 0
    try:
        return int(fields[1])
    except ValueError:
        return 0


def scrub(text):
    lower = text.lower()
    if any(word in lower for word in ("bearer ", "authorization:", "api_key", "apikey", "halbot_serve_token", "secret=")):
        return ""
    out = []
    for ch in text:
        if ch == "\n" or 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            out.append(" ")
    return "".join(out).strip()


def tail_lines(path, size):
    try:
        handle = open(path, "rb")
    except OSError:
        return []
    try:
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        handle.seek(max(0, end - size))
        data = handle.read()
    finally:
        handle.close()
    text = data.decode("utf-8", "replace")
    if end > size:
        text = text.split("\n", 1)[-1]
    return text.splitlines()


def keep_milestone(line):
    line = scrub(line)
    if not line:
        return ""
    if line.startswith("[TOOL_CALL ") or line.startswith("[TOOL_RESULT "):
        tool = ""
        ok = ""
        for part in line.replace("]", " ").split():
            if part.startswith("tool="):
                tool = part[5:][:40]
            elif part.startswith("ok="):
                ok = part[3:]
        if not tool:
            return ""
        if line.startswith("[TOOL_CALL "):
            return "tool " + tool
        return "tool %s done ok=%s" % (tool, ok or "?")
    if line.startswith("[worker] ") or line.startswith("[think] cot chars="):
        if "stream readline" in line or "stream first line" in line:
            return ""
        return line[:180]
    if line.startswith("[init] ConnectProxy=") or line.startswith("[init] no AgentProxy"):
        return line[:180]
    return ""


def newest_session_log():
    directory = os.path.expanduser("~/.halcode/logs")
    best = ""
    best_mtime = -1
    try:
        names = os.listdir(directory)
    except OSError:
        return ""
    for name in names:
        if not (name.startswith("session_") and name.endswith(".txt")):
            continue
        path = os.path.join(directory, name)
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue
        if mtime > best_mtime:
            best_mtime = mtime
            best = path
    return best


def main():
    btime = boot_time()
    serve_pid = 0
    agent_pid = 0
    spec = ""
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        cmd = cmdline(pid)
        if "HalCode9000" not in cmd:
            continue
        if "--serve" in cmd.split():
            serve_pid = pid
        elif "--agent" in cmd.split():
            agent_pid = pid
            parts = cmd.split()
            at = parts.index("--agent")
            if at + 1 < len(parts):
                spec = parts[at + 1][:80]

    phase = "idle"
    curl = False
    if agent_pid:
        phase = "working"
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            pid = int(name)
            if ppid_of(pid) != agent_pid:
                continue
            child = cmdline(pid)
            if child.startswith("/usr/bin/curl") or child.split(" ")[0].endswith("/curl") or child.startswith("curl "):
                curl = True
        if curl:
            phase = "calling the provider"

    log_path = "/tmp/hal_serve.log"
    try:
        log_bytes = os.path.getsize(log_path)
    except OSError:
        log_bytes = 0
    milestones = []
    stream_lines = 0
    for line in tail_lines(log_path, 65536):
        if "[init] agent mode detected" in line or "[worker] done" in line:
            milestones = []
            stream_lines = 0
            continue
        if "stream readline" in line:
            stream_lines += 1
            continue
        item = keep_milestone(line)
        if item:
            milestones.append(item)
    session = newest_session_log()
    if session:
        for line in tail_lines(session, 131072):
            item = keep_milestone(line)
            if item and item.startswith("tool "):
                milestones.append(item)
    tools = []
    for line in tail_lines("/tmp/hal9000_debug.log", 65536):
        line = scrub(line)
        if line.startswith("Dispatching tool [") and line.endswith("]"):
            name = line[len("Dispatching tool ["):-1]
            safe = name != "" and len(name) <= 40
            for ch in name:
                letter = ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9")
                if not (letter or ch in "_-"):
                    safe = False
            if safe:
                tools.append("dispatch " + name)
        elif line.startswith("Tool [") and "] returned." in line:
            tools.append(line[:140])
        elif line.startswith("Model requested "):
            tools.append(line[:80])
    if not any("Request OK" in item for item in milestones):
        tools = []
    recent = milestones[-12:]
    tools = tools[-8:]
    elapsed = elapsed_sec(agent_pid, btime) if agent_pid else 0

    think = ""
    think_age = None
    think_path = "/tmp/halcode_app/think.txt"
    try:
        st = os.stat(think_path)
        think_age = max(0, int(time.time() - st.st_mtime))
        raw = tail_lines(think_path, 4096)
        think = scrub(" ".join(part.strip() for part in raw if part.strip()))
        if len(think) > 400:
            think = think[-400:]
        if agent_pid and think_age is not None and think_age > elapsed + 3:
            think = ""
            think_age = None
    except OSError:
        think = ""

    report = {
        "ok": True,
        "serve": bool(serve_pid),
        "busy": bool(agent_pid),
        "spec": spec,
        "elapsed_sec": elapsed,
        "phase": phase,
        "log_bytes": log_bytes,
        "stream_lines": stream_lines,
        "recent": recent,
        "tools": tools,
        "think_age_sec": think_age,
        "think_tail": think,
    }
    print(json.dumps(report), end="")


main()
