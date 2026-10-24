#!/usr/bin/env python3
"""Local HalBot window. Serves the page on 127.0.0.1 and proxies the bot API.

The browser stays on this origin. /healthz and /v1/* are forwarded to the
guest, which QEMU publishes at 127.0.0.1:8080. This process adds the guest
serve token itself. Provider keys posted to /local/keys are written on the
guest and are not stored in the browser or in this process's log.
"""
import base64
import json
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("HALBOT_UPSTREAM", "http://127.0.0.1:8080").rstrip("/")
BIND = "127.0.0.1"
PORT = int(os.environ.get("HALBOT_PAGE_PORT", "8090"))
ROOT = os.path.dirname(os.path.abspath(__file__))
VM_DIR = os.environ.get("HALBOT_VM_DIR", os.path.abspath(os.path.join(ROOT, "..", "vm")))
SSH = [
    "ssh",
    "-i", os.environ.get("HALBOT_SSH_KEY", os.path.join(VM_DIR, "keys", "id_ed25519")),
    "-p", os.environ.get("HALBOT_SSH_PORT", "2222"),
    "-o", "UserKnownHostsFile=" + os.environ.get(
        "HALBOT_KNOWN_HOSTS", os.path.join(VM_DIR, "keys", "known_hosts")
    ),
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
    os.environ.get("HALBOT_SSH_DEST", "halbot@127.0.0.1"),
]
# Page id -> guest file under ~/.halcode/. Auth reads ~/.halcode/<hint>_key.
KEY_FILES = {
    "grok": "xai_key",
    "deepseek": "deepseek_key",
    "anthropic": "anthropic_key",
}
_TOKEN = {"value": ""}


def _ssh(remote_code, stdin_bytes=None, timeout=15):
    # The guest shell parses the remote command, so the program has to be
    # one quoted argument. The key bytes stay on stdin, not in the command.
    encoded = base64.b64encode(remote_code.encode("utf-8")).decode("ascii")
    one = "import base64; exec(base64.b64decode('%s'))" % encoded
    proc = subprocess.run(
        SSH + ["python3 -c " + shlex.quote(one)],
        input=stdin_bytes,
        capture_output=True,
        timeout=timeout,
    )
    return proc


def guest_token():
    if _TOKEN["value"]:
        return _TOKEN["value"]
    code = (
        "import os, sys\n"
        "p=os.path.expanduser('~/.halcode/keys.env')\n"
        "tok=''\n"
        "try:\n"
        "    f=open(p)\n"
        "except OSError:\n"
        "    f=None\n"
        "if f:\n"
        "    for line in f:\n"
        "        if line.startswith('HALBOT_SERVE_TOKEN='):\n"
        "            tok=line.split('=',1)[1].strip()\n"
        "            break\n"
        "    f.close()\n"
        "sys.stdout.write(tok)\n"
    )
    try:
        proc = _ssh(code, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    val = proc.stdout.decode("utf-8", "replace").strip()
    if val:
        _TOKEN["value"] = val
    return _TOKEN["value"]


def key_status():
    code = (
        "import os, sys\n"
        "home=os.path.expanduser('~/.halcode')\n"
        "names=('xai_key','deepseek_key','anthropic_key')\n"
        "for name in names:\n"
        "    path=os.path.join(home, name)\n"
        "    ok=os.path.isfile(path) and os.path.getsize(path)>0\n"
        "    sys.stdout.write(name + (' 1\\n' if ok else ' 0\\n'))\n"
    )
    proc = _ssh(code, timeout=10)
    if proc.returncode != 0:
        raise OSError("guest key status failed")
    present = {}
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) == 2:
            present[parts[0]] = parts[1] == "1"
    out = {}
    for prov, filename in KEY_FILES.items():
        out[prov] = bool(present.get(filename))
    return out


def check_key(value):
    if not isinstance(value, str):
        return "each key must be text"
    text = value.strip()
    if not text:
        return ""
    if any(ch in text for ch in ("\n", "\r", "\t", " ")):
        return "a key must be one line with no spaces"
    if len(text) > 250:
        return "a key must be 250 characters or less"
    return ""


def save_keys(payload):
    clean = {}
    for prov in KEY_FILES:
        if prov not in payload:
            continue
        err = check_key(payload.get(prov))
        if err:
            raise ValueError(err)
        text = payload.get(prov)
        if isinstance(text, str) and text.strip():
            clean[prov] = text.strip()
    if not clean:
        return []
    code = (
        "import json, os, sys\n"
        "allowed={'grok':'xai_key','deepseek':'deepseek_key','anthropic':'anthropic_key'}\n"
        "body=json.load(sys.stdin)\n"
        "home=os.path.expanduser('~/.halcode')\n"
        "os.makedirs(home, 0o700, exist_ok=True)\n"
        "saved=[]\n"
        "for prov, name in allowed.items():\n"
        "    raw=body.get(prov) or ''\n"
        "    if not isinstance(raw, str):\n"
        "        sys.exit(2)\n"
        "    raw=raw.strip()\n"
        "    if not raw:\n"
        "        continue\n"
        "    if any(c in raw for c in '\\n\\r\\t '):\n"
        "        sys.exit(3)\n"
        "    if len(raw)>250:\n"
        "        sys.exit(4)\n"
        "    path=os.path.join(home, name)\n"
        "    fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)\n"
        "    try:\n"
        "        os.write(fd, (raw+'\\n').encode())\n"
        "    finally:\n"
        "        os.close(fd)\n"
        "    os.chmod(path, 0o600)\n"
        "    saved.append(prov)\n"
        "sys.stdout.write(' '.join(saved))\n"
    )
    proc = _ssh(code, json.dumps(clean).encode("utf-8"), timeout=15)
    if proc.returncode != 0:
        raise OSError("guest key write failed")
    written = [p for p in proc.stdout.decode("utf-8", "replace").split() if p in KEY_FILES]
    return written


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/local/keys":
            self._key_status()
            return
        if path == "/healthz" or path.startswith("/v1/"):
            self._proxy(timeout=5)
            return
        if path in ("/", "/index.html"):
            self._file("index.html", "text/html; charset=utf-8")
            return
        self.send_error(404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/local/keys":
            self._key_save()
            return
        if path == "/v1/chat" or (path.startswith("/v1/sessions/") and path.endswith("/messages")):
            self._proxy(timeout=360)
            return
        self.send_error(404)

    def _json(self, status, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _key_status(self):
        try:
            self._json(200, key_status())
        except (OSError, subprocess.TimeoutExpired):
            self._json(502, {"ok": False, "error": "could not read the bot"})

    def _key_save(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length < 0 or length > 8192:
            self._json(400, {"ok": False, "error": "key upload is too large"})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8") if raw else "{}")
        except (UnicodeError, json.JSONDecodeError):
            self._json(400, {"ok": False, "error": "keys must be JSON"})
            return
        if not isinstance(payload, dict):
            self._json(400, {"ok": False, "error": "keys must be a JSON object"})
            return
        try:
            saved = save_keys(payload)
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        except (OSError, subprocess.TimeoutExpired):
            self._json(502, {"ok": False, "error": "could not save keys on the bot"})
            return
        self._json(200, {"ok": True, "saved": saved})

    def _file(self, name, content_type):
        data = open(os.path.join(ROOT, name), "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self, timeout):
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else None
        headers = {}
        if self.headers.get("Content-Type"):
            headers["Content-Type"] = self.headers["Content-Type"]
        if self.path.split("?", 1)[0].startswith("/v1/"):
            token = guest_token()
            if token:
                headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(
            UPSTREAM + self.path, data=body, headers=headers, method=self.command
        )
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            resp = exc
        except Exception:
            msg = b'{"ok":false,"error":"halbot unreachable"}'
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
        payload = resp.read()
        self.send_response(resp.status)
        ctype = resp.headers.get("Content-Type", "application/json")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main():
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print("HalBot window at http://%s:%d/" % (BIND, PORT), flush=True)
    print("proxying the bot at %s" % UPSTREAM, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
