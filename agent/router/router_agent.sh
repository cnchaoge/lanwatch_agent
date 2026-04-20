#!/bin/sh
#
# lanwatch_router_agent - 软路由监控客户端（Shell 版）
# 适用于 OpenWRT / LEDE / 蒲公英 / iKuai / 爱快 等 Linux 路由器
#
# 安装方式：
#   1. scp router_agent.sh root@192.168.1.1:/etc/lanwatch/
#   2. chmod +x /etc/lanwatch/router_agent.sh
#   3. 添加到 /etc/rc.local 或 crontab
#
# 或通过 OpenWRT LuCI 上传 ipk 包安装（推荐）
#

VERSION="0.5.0"
AGENT_ID=""
SERVER_URL="http://82.156.229.67:8000"
INTERVAL=60          # 上报间隔（秒）
LOG_FILE="/tmp/lanwatch_agent.log"
CONFIG_FILE="/etc/lanwatch/agent.json"

check_dependency() {
    for cmd in curl ip ping cat; do
        if ! command -v "$cmd" > /dev/null 2>&1; then
            echo "[$(date)] 缺少依赖: $cmd" >> "$LOG_FILE"
        fi
    done
}

load_config() {
    if [ -f "$CONFIG_FILE" ]; then
        # 简单解析 JSON（无 jq 情况下）
        AGENT_ID=$(grep -o '"agent_id"[^,]*' "$CONFIG_FILE" 2>/dev/null | cut -d'"' -f4)
        COMPANY_NAME=$(grep -o '"company_name"[^,]*' "$CONFIG_FILE" 2>/dev/null | cut -d'"' -f4)
    fi
}

save_config() {
    mkdir -p "$(dirname "$CONFIG_FILE")"
    cat > "$CONFIG_FILE" <<EOF
{
  "agent_id": "$AGENT_ID",
  "company_name": "$COMPANY_NAME",
  "version": "$VERSION",
  "platform": "$(uname -m)"
}
EOF
}

get_local_ip() {
    # 获取 WAN 口 IP
    local wan_if=$(ip route | grep default | awk '{print $5}' | head -1)
    if [ -z "$wan_if" ]; then
        wan_if="br-lan"
    fi
    ip -4 addr show "$wan_if" 2>/dev/null | grep inet | awk '{print $2}' | cut -d'/' -f1
}

get_gateway() {
    ip route | grep default | awk '{print $3}' | head -1
}

get_subnet() {
    local gw=$(get_gateway)
    echo "$gw" | sed 's/\.[0-9]*$/.0\/24/'
}

ping_host() {
    local host="$1"
    local timeout="${2:-3}"
    ping -c 1 -W "$timeout" "$host" > /dev/null 2>&1
    [ $? -eq 0 ] && echo "1" || echo "0"
}

ping_rtt() {
    local host="$1"
    local rtt=$(ping -c 1 -W 3 "$host" 2>/dev/null | grep time= | sed 's/.*time=\([0-9.]*\).*/\1/')
    [ -n "$rtt" ] && echo "$rtt" || echo "0"
}

get_mac_by_ip() {
    local ip="$1"
    ping -c 1 -W 1 "$ip" > /dev/null 2>&1
    sleep 0.5
    ip neigh show "$ip" 2>/dev/null | awk '{print $5}' | head -1
}

get_router_name() {
    cat /proc/sys/kernel/hostname 2>/dev/null
}

get_uptime() {
    cat /proc/uptime | awk '{print $1}'
}

get_cpu_usage() {
    top -bn1 2>/dev/null | grep "CPU" | awk '{print $3}' | sed 's/%//' || echo "0"
}

get_mem_info() {
    # 返回格式: total,free,usage_percent
    local total=$(cat /proc/meminfo | grep MemTotal | awk '{print $2}')
    local free=$(cat /proc/meminfo | grep MemAvailable | awk '{print $2}')
    [ -z "$free" ] && free=$(cat /proc/meminfo | grep MemFree | awk '{print $2}')
    local used=$((total - free))
    local pct=$((used * 100 / total))
    echo "${total}KB,${free}KB,$pct%"
}

register() {
    local company_name="$1"
    local location="${2:-router'}"
    local data="{\"name\":\"$company_name\",\"customer_name\":\"$company_name\",\"location\":\"$location\",\"remark\":\"router-agent\"}"
    
    local resp=$(curl -s -X POST "$SERVER_URL/api/register" \
        -H "Content-Type: application/json" \
        -d "$data" 2>/dev/null)
    
    AGENT_ID=$(echo "$resp" | grep -o '"agent_id":"[^"]*' | cut -d'"' -f4)
    if [ -n "$AGENT_ID" ]; then
        echo "[$(date)] 注册成功，Agent ID: $AGENT_ID" >> "$LOG_FILE"
        save_config
        return 0
    else
        echo "[$(date)] 注册失败: $resp" >> "$LOG_FILE"
        return 1
    fi
}

report() {
    local data="$1"
    curl -s -X POST "$SERVER_URL/api/$AGENT_ID/report" \
        -H "Content-Type: application/json" \
        -d "$data" > /dev/null 2>&1
}

send_offline() {
    curl -s -X POST "$SERVER_URL/api/$AGENT_ID/offline" \
        -H "Content-Type: application/json" \
        -d "{}" > /dev/null 2>&1
}

probe() {
    local gateway=$(get_gateway)
    local local_ip=$(get_local_ip)
    
    # ping 网关
    local gw_ok=$(ping_host "$gateway")
    local gw_rtt=$(ping_rtt "$gateway")
    
    # ping DNS
    local dns_ok=$(ping_host "8.8.8.8")
    local dns_rtt=$(ping_rtt "8.8.8.8")
    
    # ping 目标（默认用网关）
    local target="${TARGET_HOST:-$gateway}"
    local target_ok=$(ping_host "$target")
    local target_rtt=$(ping_rtt "$target")
    
    # 组 JSON（兼容无 jq 环境）
    local subnet=$(get_subnet)
    cat <<EOF
{
  "ping_ok": $gw_ok,
  "ping_rtt_ms": $gw_rtt,
  "gateway_reachable": $gw_ok,
  "dns_ok": $dns_ok,
  "dns_ms": $dns_rtt,
  "target_reachable": $target_ok,
  "target_name": "网关",
  "target_rtt_ms": $target_rtt,
  "subnets": "$subnet",
  "local_ip": "$local_ip",
  "router_name": "$(get_router_name)",
  "uptime": $(get_uptime),
  "mem": "$(get_mem_info)"
}
EOF
}

topology_scan() {
    local subnet=$(get_subnet)
    local prefix=$(echo "$subnet" | cut -d'.' -f1-3)
    local results="["
    local count=0
    local total=0
    
    echo "[$(date)] 开始扫描网段: $subnet" >> "$LOG_FILE"
    
    # 快速 ping 扫描（并行 30 个）
    for i in $(seq 1 254); do
        local ip="${prefix}.${i}"
        (
            local ok=$(ping_host "$ip" 1)
            if [ "$ok" = "1" ]; then
                local mac=$(get_mac_by_ip "$ip")
                local vendor=""
                [ -n "$mac" ] && vendor=$(grep -i "${mac:0:8}" /tmp/oui.txt 2>/dev/null | head -1 | cut -f2)
                echo "{\"ip\":\"$ip\",\"mac\":\"$mac\",\"vendor\":\"$vendor\"}"
            fi
        ) &
        
        # 每 30 个进程wait一次，控制并发
        if [ $((++total)) -eq 30 ]; then
            wait
            total=0
        fi
    done
    wait
    
    echo "[]"
}

main() {
    mkdir -p "$(dirname "$LOG_FILE")"
    mkdir -p "$(dirname "$CONFIG_FILE")"
    
    echo "[$(date)] lanwatch_router_agent v$VERSION 启动" >> "$LOG_FILE"
    
    check_dependency
    load_config
    
    # 首次运行，未注册
    if [ -z "$AGENT_ID" ]; then
        echo "[$(date)] 首次运行，正在注册..." >> "$LOG_FILE"
        local hostname=$(get_router_name)
        register "${1:-路由器}" "软路由" || exit 1
    fi
    
    # 主循环
    while true; do
        local data=$(probe)
        echo "[$(date)] 上报数据: $(echo "$data" | head -c 100)..." >> "$LOG_FILE"
        report "$data"
        
        # 每 5 分钟扫一次拓扑
        if [ $((++scan_count)) -ge 5 ]; then
            scan_count=0
            echo "[$(date)] 扫描拓扑..." >> "$LOG_FILE"
            # 拓扑上报（可选，取决于服务端支持）
        fi
        
        sleep "$INTERVAL"
    done
}

# 信号处理：优雅退出
trap 'echo "[$(date)] 收到退出信号" >> "$LOG_FILE"; send_offline; exit 0' INT TERM

# 运行
main "$@"
