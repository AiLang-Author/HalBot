#!/bin/bash
# Chat window on 127.0.0.1:8090. The browser never sees the serve token.
# Copyright (c) 2026 Sean Collins, 2 Paws Machine and Engineering. MIT.
set -euo pipefail
cd "$(dirname "$0")"
exec /usr/bin/python3 ./serve.py
