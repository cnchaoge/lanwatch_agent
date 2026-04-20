#!/bin/sh
#
# LanWatch 软路由客户端安装脚本
# 支持：OpenWRT / LEDE / 蒲公英 / iKuai
#
# 用法：
#   cat install.sh | ssh root@192.168.1.1
#   或
#   scp -r router/* root@192.168.1.1:/tmp/lanwatch_install/
#   ssh root@192.168.1.1
#   cd /tmp/lanwatch_install && sh install.sh

set -e

echo "======================================"
echo " LanWatch 软路由客户端安装脚本"
echo "======================================"
echo

# 检测平台
detect_platform() {
    if [ -f /etc/openwrt_release ]; then
        echo "检测到: OpenWRT"
        PLATFORM="openwrt"
    elif grep -q "iKuai" /tmp/version 2>/dev/null; then
        echo "检测到: iKuai"
        PLATFORM="ikuai"
    elif [ -f /etc/lede_release ]; then
        echo "检测到: LEDE"
        PLATFORM="lede"
    elif command -v ikuaictl >/dev/null 2>&1; then
        echo "检测到: iKuai"
        PLATFORM="ikuai"
    else
        echo "检测到: 通用 Linux"
        PLATFORM="generic"
    fi
}

# 安装目录
INSTALL_DIR="/etc/lanwatch"
mkdir -p "$INSTALL_DIR"

# 复制 agent 脚本
echo "[1/4] 复制 agent 脚本..."
cp router_agent.sh "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/router_agent.sh"

# OpenWRT 安装
install_openwrt() {
    echo "[2/4] OpenWRT 平台配置..."

    # 复制 init 脚本
    cp lanwatch.init /etc/init.d/lanwatch
    chmod +x /etc/init.d/lanwatch

    # 开机自启
    /etc/init.d/lanwatch enable
    echo "已启用开机自启（/etc/init.d/lanwatch）"

    # 检查依赖
    for pkg in curl ip; do
        if ! command -v "$pkg" > /dev/null 2>&1; then
            echo "提示：建议安装 $pkg: opkg install $pkg"
        fi
    done
}

# iKuai 安装
install_ikuai() {
    echo "[2/4] iKuai 平台配置..."
    # iKuai 有自己的启动脚本系统，这里用 cron 代替
    mkdir -p /etc/crontabs/root
    echo "*/5 * * * * /etc/lanwatch/router_agent.sh >> /tmp/lanwatch_agent.log 2>&1" >> /etc/crontabs/root
    crond -f &
    echo "已配置定时任务（每5分钟执行）"
}

# 通用 Linux 安装
install_generic() {
    echo "[2/4] 通用 Linux 配置..."
    mkdir -p /etc/cron.d
    echo "*/5 * * * * root /etc/lanwatch/router_agent.sh >> /tmp/lanwatch_agent.log 2>&1" > /etc/cron.d/lanwatch
    chmod +x /etc/lanwatch/router_agent.sh
    echo "已配置 crontab 定时任务（每5分钟执行）"
}

# 防火墙放行（OpenWRT）
configure_firewall() {
    echo "[3/4] 配置防火墙..."
    # 放行 82.156.229.67 的 TCP 连接
    uci add firewall rule >/dev/null 2>&1 || true
    uci set firewall.@rule[-1].name='Allow-LanWatch'
    uci set firewall.@rule[-1].src='wan'
    uci set firewall.@rule[-1].dest_ip='82.156.229.67'
    uci set firewall.@rule[-1].dest_port='80'
    uci commit firewall
    /etc/init.d/firewall reload >/dev/null 2>&1 || true
}

# 启动
start_agent() {
    echo "[4/4] 启动 agent..."
    case "$PLATFORM" in
        openwrt)
            /etc/init.d/lanwatch start
            ;;
        ikuai|generic)
            nohup /etc/lanwatch/router_agent.sh > /tmp/lanwatch_agent.log 2>&1 &
            echo "Agent 已启动"
            ;;
    esac
}

# 主流程
detect_platform

case "$PLATFORM" in
    openwrt)
        install_openwrt
        configure_firewall
        ;;
    ikuai)
        install_ikuai
        ;;
    lede)
        install_openwrt
        ;;
    *)
        install_generic
        ;;
esac

start_agent

echo
echo "======================================"
echo " 安装完成！"
echo "======================================"
echo
echo "查看日志：tail -f /tmp/lanwatch_agent.log"
echo "停止服务：killall router_agent.sh"
echo "卸载：rm -rf /etc/lanwatch /etc/init.d/lanwatch"
echo
