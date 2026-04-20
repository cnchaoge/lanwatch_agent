# 软路由器客户端

支持 OpenWRT、iKuai、LEDE、蒲公英、爱快等 Linux 软路由系统。

## 支持平台

| 平台 | 技术方案 | 部署方式 |
|------|---------|---------|
| **OpenWRT** | Shell + cron/init.d | LuCI 安装 ipk 包 |
| **LEDE** | Shell + cron/init.d | 同 OpenWRT |
| **蒲公英** | Shell + cron/init.d | SCP 部署 |
| **iKuai** | Shell + cron | SSH 部署 |
| **爱快** | Shell + cron | SSH 部署 |

## 目录结构

```
router/
├── router_agent.sh      # 核心 agent（Shell 脚本，零依赖）
├── lanwatch.init        # OpenWRT /etc/init.d/ 启动脚本
├── install.sh           # 自动安装脚本（跨平台）
├── Makefile            # OpenWRT ipk 编译文件
└── luci-app-lanwatch/  # LuCI Web 管理界面
    ├── Makefile
    ├── root/
    │   ├── etc/config/lanwatch    # UCI 配置
    │   └── usr/lib/lua/luci/
    │       ├── controller/lanwatch.lua  # LuCI 控制器
    │       └── model/cbi/lanwatch.lua  # LuCI 配置页
    └── README.md
```

## 快速安装

### 方式一：SCP 部署（通用，推荐）

```bash
# 在本地执行，把文件传到路由器
scp -r router root@192.168.1.1:/tmp/lanwatch_install/
ssh root@192.168.1.1
cd /tmp/lanwatch_install && sh install.sh
```

### 方式二：OpenWRT LuCI 安装 ipk（推荐有编译条件的人）

```bash
# 在 OpenWRT SDK 环境下编译
make package/luci-app-lanwatch/compile

# 在路由器上
opkg install luci-app-lanwatch_*.ipk
```

### 方式三：手动逐台安装

```bash
# SSH 登录路由器
ssh root@192.168.1.1

# 创建目录
mkdir -p /etc/lanwatch

# 复制并编辑配置
vim /etc/lanwatch/router_agent.sh   # 填入公司名称
chmod +x /etc/lanwatch/router_agent.sh

# 加入 crontab（每5分钟执行）
echo "*/5 * * * * /etc/lanwatch/router_agent.sh >> /tmp/lanwatch_agent.log 2>&1" >> /etc/crontabs/root
```

## agent 工作原理

```
┌──────────────────────────────────────┐
│  软路由（OpenWRT / iKuai 等）         │
│                                      │
│  router_agent.sh                     │
│   ├── 每 60s ping 检测（网关/DNS）   │
│   ├── 每 5 分钟扫描局域网拓扑        │
│   ├── 上报到云端服务器              │
│   └── 掉线时通知服务端              │
└──────────────┬───────────────────────┘
               │ HTTP POST (每 60s)
               ▼
┌──────────────────────────────────────┐
│  云端服务器 (82.156.229.67)           │
│                                      │
│  FastAPI 服务端                      │
│   ├── 接收数据写入 SQLite            │
│   ├── SSE 实时推送管理后台           │
│   └── 离线超过 3 分钟 → 微信报警     │
└──────────────────────────────────────┘
```

## 已知限制

- Shell 脚本依赖 `curl`、`ip`、`ping` 等基础命令（大多数路由器自带）
- 无 LuCI 界面时，需手动编辑配置
- iKuai/爱快 暂不支持 LuCI，需 SSH 部署
- 内存小于 32MB 的老路由器可能跑不动

## OpenWRT 依赖

```bash
opkg update && opkg install curl ip bash
```

## 卸载

```bash
# OpenWRT
/etc/init.d/lanwatch disable
/etc/init.d/lanwatch stop
rm -f /etc/init.d/lanwatch /etc/lanwatch/router_agent.sh

# 通用
killall router_agent.sh
rm -rf /etc/lanwatch
crontab -e  # 删除对应行
```
