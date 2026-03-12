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

# 注册 MCP 到 OpenClaw
OPENCLAW_CONFIG="$HOME/.openclaw/openclaw.json"
PYTHON_PATH="$SCRIPT_DIR/.venv/bin/python"
SERVER_PATH="$SCRIPT_DIR/server.py"

if [ -f "$OPENCLAW_CONFIG" ]; then
    if python3 -c "
import json, sys
with open('$OPENCLAW_CONFIG') as f:
    cfg = json.load(f)
servers = cfg.get('mcpServers', {})
if 'bom-assistant' not in servers:
    servers['bom-assistant'] = {
        'command': '$PYTHON_PATH',
        'args': ['$SERVER_PATH']
    }
    cfg['mcpServers'] = servers
    with open('$OPENCLAW_CONFIG', 'w') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print('OK')
else:
    print('EXIST')
"; then
        echo "[*] MCP 已注册到 OpenClaw"
    fi
else
    mkdir -p "$(dirname "$OPENCLAW_CONFIG")"
    echo "{\"mcpServers\":{\"bom-assistant\":{\"command\":\"$PYTHON_PATH\",\"args\":[\"$SERVER_PATH\"]}}}" | python3 -m json.tool > "$OPENCLAW_CONFIG"
    echo "[*] 已创建 OpenClaw 配置并注册 MCP"
fi

echo "[*] 安装完成。请确保 .env 已配置，然后重启 OpenClaw。"
