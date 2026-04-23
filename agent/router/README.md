# OpenWrt / 路由器 Shell 客户端

> **设备支持备注**：本次更新（v0.6.4+）仅针对 **Xiaomi Redmi Router AX6000** 测试通过。

- OpenWrt / LEDE
- x86 软路由
- 常见 Linux 路由器环境

目标不是照搬 Windows 客户端，而是把**出口视角**监控先跑通。

---

## 1. 当前能力

### 已实现
- 企业首次注册（`/api/register`）
- 保存 `agent_id` / `token` 到 UCI 配置
- 每 60 秒周期上报
- 网关 ICMP 探测
- 外部目标探测（默认 `223.5.5.5`）
- 4 组 DNS 解析延迟（百度 / 阿里 / 腾讯 / 网易）
- 路由器子网信息上报
- `ip neigh show` 静默拓扑上报
- 连续失败达到阈值后执行 `traceroute`
- OpenWrt `init.d + procd` 常驻守护

### 暂未实现
- LuCI 图形界面
- ipk 打包脚本
- 设备类型识别 / 厂商识别
- 更精细的 DNS 延迟测量（当前是 shell 版 best effort）

---

## 2. 文件说明

```text
agent/router/
├── router_agent.sh   # 主脚本（shell agent）
├── lanwatch.init     # OpenWrt /etc/init.d/lanwatch
├── lanwatch.config   # /etc/config/lanwatch 默认配置模板
├── install.sh        # 安装脚本
└── README.md
```

---

## 3. 安装方式

### OpenWrt / LEDE

```bash
scp -r agent/router root@192.168.1.1:/tmp/lanwatch
ssh root@192.168.1.1
cd /tmp/lanwatch
sh install.sh
```

安装完成后：

```bash
uci set lanwatch.main.company_name='你的企业名'
uci commit lanwatch
/etc/init.d/lanwatch restart
```

---

## 4. 配置文件

路径：`/etc/config/lanwatch`

示例：

```sh
config lanwatch 'main'
    option enabled '1'
    option server 'http://82.156.229.67:8000'
    option company_name '我的企业'
    option phone ''
    option interval '60'
    option topology_interval '300'
    option diag_fail_count '3'
    option target_host '223.5.5.5'
    option agent_id ''
    option token ''
```

---

## 5. 常用命令

```bash
# 服务管理
/etc/init.d/lanwatch start
/etc/init.d/lanwatch stop
/etc/init.d/lanwatch restart
/etc/init.d/lanwatch enable

# 单次执行探测
/usr/bin/lanwatch_router_agent.sh once

# 仅执行注册
/usr/bin/lanwatch_router_agent.sh register

# 仅执行拓扑上报
/usr/bin/lanwatch_router_agent.sh topology

# 仅执行离线诊断
/usr/bin/lanwatch_router_agent.sh diag

# 查看日志
tail -f /tmp/lanwatch_agent.log
```

---

## 6. 依赖建议

最小依赖：

- `ping`
- `ip`
- `awk`
- `sed`
- `date`
- `curl` 或 `wget`

OpenWrt 推荐：

```bash
opkg update
opkg install curl ip-full traceroute
```

如果没有 `traceroute`，客户端仍可运行，只是离线诊断会降级为“上报缺少 traceroute”。

---

## 7. 产品定位

建议把它定义成：

- **Windows 客户端**：终端视角
- **OpenWrt 客户端**：出口 / 核心视角
- **SNMP**：企业设备视角

这样三层互补，LANWatch 才真正像一个完整的企业网络值守平台。
