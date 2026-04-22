#!/bin/sh
# LanWatch OpenWrt / Router shell agent installer

set -e

INSTALL_DIR="/etc/lanwatch"
BIN_PATH="/usr/bin/lanwatch_router_agent.sh"
INIT_PATH="/etc/init.d/lanwatch"
CONFIG_DST="/etc/config/lanwatch"

say() {
    echo "$*"
}

need_root() {
    if [ "$(id -u)" != "0" ]; then
        echo "请使用 root 执行安装"
        exit 1
    fi
}

install_files() {
    mkdir -p "$INSTALL_DIR"
    cp router_agent.sh "$BIN_PATH"
    chmod +x "$BIN_PATH"

    cp lanwatch.init "$INIT_PATH"
    chmod +x "$INIT_PATH"

    if [ ! -f "$CONFIG_DST" ]; then
        cp lanwatch.config "$CONFIG_DST"
        say "已写入默认配置: $CONFIG_DST"
    else
        say "保留已有配置: $CONFIG_DST"
    fi
}

check_deps() {
    local missing=""
    for cmd in ping ip awk sed date; do
        command -v "$cmd" >/dev/null 2>&1 || missing="$missing $cmd"
    done

    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
        missing="$missing curl/wget"
    fi

    if [ -n "$missing" ]; then
        say "警告：当前缺少依赖:$missing"
        say "OpenWrt 建议安装：opkg update && opkg install curl ip-full"
    fi
}

enable_service() {
    "$INIT_PATH" enable >/dev/null 2>&1 || true
    "$INIT_PATH" restart
}

show_next_steps() {
    cat <<EOF

安装完成。

配置文件：$CONFIG_DST
主程序：  $BIN_PATH
日志文件：/tmp/lanwatch_agent.log

常用命令：
  uci show lanwatch
  /etc/init.d/lanwatch start
  /etc/init.d/lanwatch stop
  /etc/init.d/lanwatch restart
  /usr/bin/lanwatch_router_agent.sh once
  tail -f /tmp/lanwatch_agent.log

首次使用请至少配置：
  uci set lanwatch.main.company_name='你的企业名'
  uci commit lanwatch
  /etc/init.d/lanwatch restart
EOF
}

need_root
say "== LanWatch 路由器 Shell 客户端安装 =="
install_files
check_deps
enable_service
show_next_steps
