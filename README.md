# 🔭 Lanwatch

企业级网络监控平台 — 面向中小企业的轻量级网络监控工具，支持探针上报、SNMP 轮询、拓扑发现、告警推送和引导式故障排查。

## ✨ 功能

| 模块 | 功能 |
|------|------|
| 🔍 探测 | ICMP / Traceroute / 端口扫描 / DNS / HTTP / SNMP |
| ⏰ 调度 | APScheduler 定时探测，按设备配置间隔 |
| 🗺️ 拓扑 | LLDP / CDP / ARP 自动发现，设备类型/厂商推断 |
| 🔔 告警 | 8 条规则 + Server酱/钉钉/飞书推送 |
| 🩺 诊断 | 12 条诊断规则 + 引导式排查向导 + 故障传播链 |
| 📊 前端 | 暗色主题，响应式，六个页面，趋势图表 |

## 🚀 快速开始

### Docker（一条命令）

```bash
git clone https://github.com/cnchaoge/lanwatch_agent.git
cd lanwatch_agent
docker-compose up -d
```

访问 http://localhost:8000

### 手动部署

```bash
cd server
pip install -r requirements.txt
export SCKEY=你的Server酱Key   # 可选
python main.py
```

访问 http://localhost:8000

### 部署 Agent

```powershell
# Windows
cd agent/windows && pip install -r requirements.txt && python main.py
```

```bash
# Linux
cd agent/linux && pip install -r requirements.txt && ./lanwatch_agent_linux.sh start

# OpenWrt 路由器
上传 router_agent.sh，执行 ./router_agent.sh install
```

## 📖 文档

- [完整文档](docs/INSTALL.md)
- [安装指南](docs/INSTALL.md)
- [常见问题](docs/FAQ.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [API 参考](docs/API.md)

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────┐
│                    Web UI (SPA)                     │
│         总览 / 设备 / 拓扑 / 告警 / 历史 / 诊断      │
└─────────────────────┬───────────────────────────────┘
                      │ HTTP REST API
┌─────────────────────▼───────────────────────────────┐
│                  FastAPI 服务端                      │
│  ┌─────────┬──────────┬──────────┬──────────────┐  │
│  │ 探测API │ 告警API  │ 拓扑API  │  诊断API     │  │
│  └────┬────┴────┬─────┴────┬─────┴──────┬───────┘  │
│       │         │          │            │           │
│  ┌────▼────┐ ┌──▼───┐ ┌───▼────┐ ┌────▼────┐       │
│  │ Ping    │ │Tracer│ │SNMP    │ │诊断引擎 │       │
│  │ Tracero │ │oute  │ │Manager │ │传播链   │       │
│  │ Portscan│ │DNS   │ │        │ │向导     │       │
│  └────┬────┘ └──┬───┘ └───┬────┘ └────┬────┘       │
│       │         │          │            │           │
│  ┌────▼─────────▼──────────▼────────────▼────┐       │
│  │         APScheduler 调度器               │       │
│  └──────────────────┬───────────────────────┘       │
│                     │                               │
│  ┌───────────────────▼───────────────────────┐       │
│  │              SQLite 数据库                 │       │
│  │  agents / probe_results / alert_log /     │       │
│  │  snmp_metrics / topology_nodes / ...       │       │
│  └────────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────┘

┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ Windows Agent│  │ Linux Agent │  │ OpenWrt     │
│   (本地PC)   │  │  (服务器)   │  │  (路由器)   │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │
       └────────────────┴────────────────┘
              HTTPS + Bearer Token
```

## 🛠️ 技术栈

- 后端：Python 3.9+ / FastAPI / APScheduler / SQLite
- 探测：ICMP / TCP / SNMP (pysnmp)
- 前端：原生 HTML5 / CSS3 / JavaScript / Chart.js
- 部署：Docker / docker-compose / Windows Service / systemd
- 测试：pytest（20+ 测试用例）

## 📦 项目结构

```
lanwatch_agent/
├── server/                 # 服务端
│   ├── main.py            # FastAPI 入口
│   ├── core/              # 配置/数据库/认证
│   ├── api/               # REST API（agents/probe/alerts/topology/diagnosis/wizard/propagation）
│   ├── modules/           # 业务模块（探测/调度/告警/拓扑/诊断）
│   ├── templates/         # Web 前端（SPA）
│   └── tests/             # pytest 测试
├── agent/
│   ├── windows/           # Windows Agent
│   ├── linux/             # Linux Agent
│   └── router/            # OpenWrt 路由器 Agent
├── docs/                  # 文档
├── docker-compose.yml     # Docker 部署
├── Dockerfile
└── README.md
```

## 🔧 配置

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| SCKEY | Server酱 Key | - |
| DINGTALK_WEBHOOK | 钉钉机器人 Webhook | - |
| FEISHU_WEBHOOK | 飞书机器人 Webhook | - |
| ADMIN_PASSWORD | Web UI 管理密码 | admin |
| CORS_ORIGINS | 允许的 CORS 源（逗号分隔） | - |

## 📄 License

MIT License
