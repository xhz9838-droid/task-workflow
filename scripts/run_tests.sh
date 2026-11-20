#!/usr/bin/env bash
# 统一测试入口：编排层 + agent-manager + HITL（一次收集，避免同名模块冲突）
set -euo pipefail
cd "$(dirname "$0")/.."
exec python -I -m pytest "$@"
