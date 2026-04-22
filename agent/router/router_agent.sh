#!/bin/sh
# lanwatch_router_agent - OpenWrt / 路由器 Shell 客户端

VERSION="0.6.4-shell"
DEFAULT_SERVER_URL="http://82.156.229.67:8000"
DEFAULT_INTERVAL=60
DEFAULT_TOPOLOGY_INTERVAL=300
DEFAULT_DIAG_FAIL_COUNT=3
DEFAULT_TARGET_HOST="223.5.5.5"
DEFAULT_DNS_DOMAINS="www.baidu.com www.aliyun.com www.qq.com www.163.com"
LOG_FILE="/tmp/lanwatch_agent.log"
STATE_FILE="/tmp/lanwatch_agent.state"
DIAG_FILE="/tmp/lanwatch_offline_diag.txt"
UCI_CONFIG="lanwatch"

AGENT_ID=""
TOKEN=""
COMPANY_NAME="路由器"
PHONE=""
SERVER_URL="$DEFAULT_SERVER_URL"
INTERVAL="$DEFAULT_INTERVAL"
TOPOLOGY_INTERVAL="$DEFAULT_TOPOLOGY_INTERVAL"
DIAG_FAIL_COUNT="$DEFAULT_DIAG_FAIL_COUNT"
TARGET_HOST="$DEFAULT_TARGET_HOST"
ENABLED=1
FAIL_COUNT=0
LAST_TOPOLOGY_TS=0

log() {
    local msg="$*"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $msg" >> "$LOG_FILE"
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

json_escape() {
    echo "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

now_ms() {
    local n
    n=$(date +%s%3N 2>/dev/null)
    case "$n" in
        *N*|"") echo $(( $(date +%s) * 1000 )) ;;
        *) echo "$n" ;;
    esac
}

http_post_json() {
    local url="$1"
    local payload="$2"
    local auth_token="$3"

    if command_exists curl; then
        if [ -n "$auth_token" ]; then
            curl -fsS -m 10 -X POST "$url" \
                -H "Content-Type: application/json" \
                -H "Authorization: Bearer $auth_token" \
                -d "$payload"
        else
            curl -fsS -m 10 -X POST "$url" \
                -H "Content-Type: application/json" \
                -d "$payload"
        fi
    elif command_exists wget; then
        if [ -n "$auth_token" ]; then
            wget -qO- \
                --header="Content-Type: application/json" \
                --header="Authorization: Bearer $auth_token" \
                --post-data="$payload" \
                "$url"
        else
            wget -qO- \
                --header="Content-Type: application/json" \
                --post-data="$payload" \
                "$url"
        fi
    else
        log "[错误] 缺少 curl/wget，无法发送请求"
        return 1
    fi
}

save_uci_value() {
    local key="$1"
    local val="$2"
    if command_exists uci; then
        uci set ${UCI_CONFIG}.main.${key}="$val" >/dev/null 2>&1 || return 1
        uci commit ${UCI_CONFIG} >/dev/null 2>&1 || return 1
    fi
}

load_uci_config() {
    if [ -f /lib/functions.sh ] && command_exists uci && uci show ${UCI_CONFIG}.main >/dev/null 2>&1; then
        . /lib/functions.sh
        config_load "$UCI_CONFIG"
        config_get ENABLED main enabled 1
        config_get SERVER_URL main server "$DEFAULT_SERVER_URL"
        config_get COMPANY_NAME main company_name "路由器"
        config_get PHONE main phone ""
        config_get INTERVAL main interval "$DEFAULT_INTERVAL"
        config_get TOPOLOGY_INTERVAL main topology_interval "$DEFAULT_TOPOLOGY_INTERVAL"
        config_get DIAG_FAIL_COUNT main diag_fail_count "$DEFAULT_DIAG_FAIL_COUNT"
        config_get TARGET_HOST main target_host "$DEFAULT_TARGET_HOST"
        config_get AGENT_ID main agent_id ""
        config_get TOKEN main token ""
    fi
}

load_state() {
    [ -f "$STATE_FILE" ] || return 0
    # shellcheck disable=SC1090
    . "$STATE_FILE"
}

save_state() {
    cat > "$STATE_FILE" <<EOF
FAIL_COUNT=${FAIL_COUNT:-0}
LAST_TOPOLOGY_TS=${LAST_TOPOLOGY_TS:-0}
EOF
}

check_dependency() {
    local missing=""
    for cmd in ping ip awk sed date; do
        command_exists "$cmd" || missing="$missing $cmd"
    done
    if [ -n "$missing" ]; then
        log "[警告] 缺少依赖:$missing"
    fi
}

get_router_name() {
    if command_exists uci; then
        uci get system.@system[0].hostname 2>/dev/null && return 0
    fi
    cat /proc/sys/kernel/hostname 2>/dev/null || echo "openwrt-router"
}

get_gateway() {
    ip route 2>/dev/null | awk '/default/ {print $3; exit}'
}

get_default_if() {
    ip route 2>/dev/null | awk '/default/ {print $5; exit}'
}

get_local_ip() {
    local iface
    iface=$(get_default_if)
    [ -n "$iface" ] || iface="br-lan"
    ip -4 addr show "$iface" 2>/dev/null | awk '/inet / {print $2}' | head -1 | cut -d/ -f1
}

get_subnets() {
    ip -4 route show 2>/dev/null | awk '/scope link/ {print $1}' | paste -sd, -
}

get_uptime_seconds() {
    awk '{print int($1)}' /proc/uptime 2>/dev/null
}

ping_stats() {
    local host="$1"
    local output
    output=$(ping -c 3 -W 2 "$host" 2>/dev/null)
    if [ -z "$output" ]; then
        echo "0||100"
        return
    fi

    local rtt
    rtt=$(echo "$output" | awk -F'/' '/min\/avg\/max/ {print $5}')
    local loss
    loss=$(echo "$output" | awk -F', ' '/packet loss/ {gsub(/%/ ,"", $3); print $3}' | awk '{print $1}')
    [ -n "$rtt" ] || rtt=""
    [ -n "$loss" ] || loss="100"
    if [ "$loss" = "100" ]; then
        echo "0||100"
    else
        echo "1|$rtt|$loss"
    fi
}

measure_dns_domain() {
    local domain="$1"
    local start end
    start=$(now_ms)
    if command_exists nslookup; then
        nslookup "$domain" >/dev/null 2>&1 || return 1
    elif command_exists ping; then
        ping -c 1 -W 2 "$domain" >/dev/null 2>&1 || return 1
    else
        return 1
    fi
    end=$(now_ms)
    echo $((end - start))
}

build_probe_json() {
    local gateway local_ip subnets dns_baidu dns_ali dns_tencent dns_163
    local ping_ok ping_rtt ping_loss target_ok target_rtt target_loss
    local ping_line target_line router_name

    gateway=$(get_gateway)
    local_ip=$(get_local_ip)
    subnets=$(get_subnets)
    router_name=$(get_router_name)

    ping_line=$(ping_stats "$gateway")
    ping_ok=$(echo "$ping_line" | cut -d'|' -f1)
    ping_rtt=$(echo "$ping_line" | cut -d'|' -f2)
    ping_loss=$(echo "$ping_line" | cut -d'|' -f3)

    target_line=$(ping_stats "$TARGET_HOST")
    target_ok=$(echo "$target_line" | cut -d'|' -f1)
    target_rtt=$(echo "$target_line" | cut -d'|' -f2)
    target_loss=$(echo "$target_line" | cut -d'|' -f3)

    dns_baidu=$(measure_dns_domain "www.baidu.com" 2>/dev/null || true)
    dns_ali=$(measure_dns_domain "www.aliyun.com" 2>/dev/null || true)
    dns_tencent=$(measure_dns_domain "www.qq.com" 2>/dev/null || true)
    dns_163=$(measure_dns_domain "www.163.com" 2>/dev/null || true)

    [ -n "$dns_baidu" ] || dns_baidu=null
    [ -n "$dns_ali" ] || dns_ali=null
    [ -n "$dns_tencent" ] || dns_tencent=null
    [ -n "$dns_163" ] || dns_163=null
    [ -n "$ping_rtt" ] || ping_rtt=null
    [ -n "$target_rtt" ] || target_rtt=null

    cat <<EOF
{
  "ping_ok": $( [ "$ping_ok" = "1" ] && echo true || echo false ),
  "ping_rtt_ms": $ping_rtt,
  "ping_loss_pct": ${ping_loss:-100},
  "dns_ms": $dns_baidu,
  "dns_ms_ali": $dns_ali,
  "dns_ms_tencent": $dns_tencent,
  "dns_ms_163": $dns_163,
  "gateway_reachable": $( [ "$ping_ok" = "1" ] && echo true || echo false ),
  "target_reachable": $( [ "$target_ok" = "1" ] && echo true || echo false ),
  "target_name": "$(json_escape "$TARGET_HOST")",
  "target_rtt_ms": $target_rtt,
  "subnets": "$(json_escape "$subnets")"
}
EOF
}

build_topology_json() {
    local first=1
    printf '{"devices":['
    ip neigh show 2>/dev/null | while read -r ip _ _ mac state _; do
        [ -n "$ip" ] || continue
        [ -n "$mac" ] || continue
        case "$state" in
            FAILED|INCOMPLETE) continue ;;
        esac
        if [ $first -eq 0 ]; then
            printf ','
        fi
        first=0
        printf '{"ip":"%s","mac":"%s","hostname":"","vendor":"","device_type":"unknown"}' \
            "$(json_escape "$ip")" "$(json_escape "$mac")"
    done
    printf ']}'
}

run_diag() {
    local target="$TARGET_HOST"
    local now_str output payload
    now_str=$(date '+%Y-%m-%d %H:%M:%S')

    if ! command_exists traceroute; then
        payload="{\"time\":\"$now_str\",\"target\":\"$(json_escape "$target")\",\"error\":\"traceroute not installed\"}"
        http_post_json "$SERVER_URL/api/$AGENT_ID/diag" "$payload" "" >/dev/null 2>&1 || true
        log "[诊断] traceroute 不存在，已上报缺失信息"
        return
    fi

    output=$(traceroute -m 10 -w 1 "$target" 2>&1 | head -20)
    printf '=== LanWatch OpenWrt 诊断 ===\n时间: %s\n目标: %s\n\n%s\n' "$now_str" "$target" "$output" > "$DIAG_FILE"

    payload="{\"time\":\"$now_str\",\"target\":\"$(json_escape "$target")\",\"error\":\"$(json_escape "$output")\"}"
    http_post_json "$SERVER_URL/api/$AGENT_ID/diag" "$payload" "" >/dev/null 2>&1 || true
    log "[诊断] 已执行 traceroute 并上报"
}

register_if_needed() {
    [ -n "$AGENT_ID" ] && return 0

    local payload resp new_agent_id new_token
    payload="{\"name\":\"$(json_escape "$COMPANY_NAME")\",\"phone\":\"$(json_escape "$PHONE")\"}"
    resp=$(http_post_json "$SERVER_URL/api/register" "$payload" "" 2>/dev/null) || {
        log "[注册] 失败：服务端不可达"
        return 1
    }

    new_agent_id=$(echo "$resp" | sed -n 's/.*"agent_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
    new_token=$(echo "$resp" | sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)

    if [ -z "$new_agent_id" ]; then
        log "[注册] 失败：$resp"
        return 1
    fi

    AGENT_ID="$new_agent_id"
    TOKEN="$new_token"
    save_uci_value agent_id "$AGENT_ID"
    [ -n "$TOKEN" ] && save_uci_value token "$TOKEN"
    log "[注册] 成功，agent_id=$AGENT_ID"
    return 0
}

report_probe() {
    local payload="$1"
    http_post_json "$SERVER_URL/api/$AGENT_ID/report" "$payload" "" >/dev/null 2>&1
}

report_topology_if_due() {
    local now_ts payload
    now_ts=$(date +%s)
    [ $((now_ts - LAST_TOPOLOGY_TS)) -lt "$TOPOLOGY_INTERVAL" ] && return 0
    payload=$(build_topology_json)
    http_post_json "$SERVER_URL/api/$AGENT_ID/topology" "$payload" "" >/dev/null 2>&1 && {
        LAST_TOPOLOGY_TS="$now_ts"
        save_state
        log "[拓扑] 已上报"
    }
}

run_once() {
    load_uci_config
    load_state

    [ "$ENABLED" = "1" ] || {
        log "[状态] 已禁用，跳过"
        return 0
    }

    register_if_needed || return 1

    local payload
    payload=$(build_probe_json)
    if report_probe "$payload"; then
        FAIL_COUNT=0
        save_state
        log "[上报] 成功"
        report_topology_if_due
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        save_state
        log "[上报] 失败，连续失败=$FAIL_COUNT"
        if [ "$FAIL_COUNT" -ge "$DIAG_FAIL_COUNT" ]; then
            run_diag
            FAIL_COUNT=0
            save_state
        fi
        return 1
    fi
}

run_loop() {
    log "[启动] lanwatch_router_agent v$VERSION"
    check_dependency
    while true; do
        run_once || true
        sleep "$INTERVAL"
    done
}

usage() {
    cat <<EOF
Usage: $0 {run|once|register|topology|diag}
  run       持续运行（默认）
  once      执行一次探测并上报
  register   仅执行注册
  topology  仅上报拓扑
  diag      仅执行离线诊断
EOF
}

cmd="${1:-run}"
case "$cmd" in
    run)
        run_loop
        ;;
    once)
        check_dependency
        load_uci_config
        load_state
        register_if_needed && run_once
        ;;
    register)
        check_dependency
        load_uci_config
        register_if_needed
        ;;
    topology)
        check_dependency
        load_uci_config
        load_state
        register_if_needed && report_topology_if_due
        ;;
    diag)
        check_dependency
        load_uci_config
        load_state
        register_if_needed && run_diag
        ;;
    *)
        usage
        exit 1
        ;;
esac
