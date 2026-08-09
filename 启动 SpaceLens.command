#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display alert "无法启动 SpaceLens" message "请先安装 Python 3，然后重新双击此程序。" as critical'
  exit 1
fi

exec python3 local_server.py
