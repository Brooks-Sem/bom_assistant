#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 创建虚拟环境
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

# 安装依赖
pip install -q -r requirements.txt

# 初始化 .env
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "[!] 已创建 .env，请编辑填入你的 API 配置"
    echo "    vi $SCRIPT_DIR/.env"
fi

echo "[*] 安装完成。请确保 .env 已配置，然后重启 OpenClaw。"
