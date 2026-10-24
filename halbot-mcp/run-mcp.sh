#!/bin/bash
# HalBot MCP server. Prefers the system Python over a toolchain python3.
# Copyright (c) 2026 Sean Collins, 2 Paws Machine and Engineering. MIT.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
py=python3
if [[ -x /usr/bin/python3 ]]; then
    py=/usr/bin/python3
fi
exec "$py" "$here/server.py"
