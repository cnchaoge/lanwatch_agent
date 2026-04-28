#!/bin/bash
# 服务健康检查脚本
set -e

BASE_URL="${1:-http://localhost:8000}"

echo "检查 Lanwatch 服务: $BASE_URL"
echo "---"

# Health
HEALTH=$(curl -s "$BASE_URL/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null)
echo "Health:  $HEALTH"

# Version
VERSION=$(curl -s "$BASE_URL/api/version" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('version','?'))" 2>/dev/null)
echo "Version: $VERSION"

# Agents
AGENTS=$(curl -s "$BASE_URL/api/agents" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('agents',d) if isinstance(d,dict) else d))" 2>/dev/null)
echo "Agents:  $AGENTS 已注册"

# Alerts
ALERTS=$(curl -s "$BASE_URL/api/alerts?limit=1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count',0))" 2>/dev/null)
echo "Alerts:  $ALERTS 条 (24h)"

# Topology
TOPO=$(curl -s "$BASE_URL/api/topology/stats" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total_nodes',0))" 2>/dev/null)
echo "Nodes:   $TOPO 个拓扑节点"

# Scheduler
JOBS=$(curl -s "$BASE_URL/api/scheduler/jobs" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count',0))" 2>/dev/null)
echo "Jobs:    $JOBS 个调度任务"

echo "---"
if [ "$HEALTH" = "ok" ]; then
    echo "✅ 服务运行正常"
else
    echo "❌ 服务异常"
    exit 1
fi
