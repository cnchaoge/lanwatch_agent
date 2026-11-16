# Lanwatch - 企业网络监控平台

Lanwatch 企业网络监控平台，一款面向中小企业的轻量级网络监控工具，支持探针上报、拓扑管理、告警推送和引导式故障排查。

## 功能特性

### 核心监控

- **多协议探测**：ICMP Ping / Traceroute / TCP 端口扫描 / DNS 解析 / HTTP 健康检查
- **定时调度**：基于 APScheduler 的灵活定时探测，支持按设备配置不同间隔
- **拓扑管理**：节点与链路持久化，支持节点详情、下游影响与按类型筛选

### 告警与诊断

- 8 条内置告警规则：设备不可达、高延迟、丢包、DNS 失败、HTTP 异常等
- 多渠道推送：Server酱 / 钉钉机器人 / 飞书机器人
- 智能诊断引擎：12 条诊断规则，自动分析根因和可能原因
- 引导式排查向导：5 个故障场景（网络/DNS/HTTP/服务/延迟），逐步引导排查
- 故障传播链：BFS 拓扑传播分析，告警 5 分钟时窗聚类

### Web 前端

- 暗色主题，响应式设计，支持移动端
- 总览 / 设备 / 拓扑 / 告警 / 历史 / 诊断 六个页面
- 实时状态和趋势图表

## 快速开始

### 环境要求

- Python 3.9+
- SQLite3
- Windows 7+ 或 Linux

### 安装服务端

```bash
cd server
pip install -r requirements.txt
```

配置（可选）：

```bash
export SCKEY=你的Server酱Key        # 告警推送
export DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
export FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
export ADMIN_PASSWORD=你的管理密码    # 默认 admin
```

启动：

```bash
python main.py
```

访问 http://localhost:8000 打开 Web UI。

### Docker 部署

```bash
docker-compose up -d
```

### Agent 部署

源码版本 1.3.0 尚未发版。已发布的 Windows 安装包是 v1.2.0。Linux / macOS / OpenWrt 没有安装包。仓库里没有 `setup.py`。

**Windows Agent**

```powershell
cd agent/windows
pip install -r requirements.txt
python main.py            # 前台
python main.py install    # 注册 Windows Service（需管理员）
```

打包：在 `agent/windows` 下执行 `pyinstaller --noconfirm --clean setup/build_spec.spec`，产物 `dist/LanwatchAgent.exe`。

**Linux Agent**

```bash
cd agent/linux
pip install pystray pillow
python3 lanwatch_agent_linux.py
```

**macOS Agent**

```bash
cd agent/mac
pip install pystray pillow
python3 lanwatch_agent_mac.py
```

**OpenWrt 路由器**

```bash
# 在 agent/router 目录的路由器副本里
sh install.sh
```

## API 参考

### 设备注册

```
POST /api/register
```

### 探测上报

```
POST /api/{agent_id}/report
POST /api/{agent_id}/topology
POST /api/{agent_id}/diag
```

### 主动探测

```
GET  /api/probe/ping?host=IP&count=4
GET  /api/probe/traceroute?host=IP
GET  /api/probe/portscan?host=IP&ports=22,80,443
GET  /api/probe/dns?domain=example.com
GET  /api/probe/http?url=https://example.com
```

### 拓扑查询

服务端不再提供 LLDP / CDP / SNMP 自动发现。下面是已上报拓扑的查询接口。

```
GET  /api/topology
GET  /api/topology/nodes
GET  /api/topology/stats
```

### 告警管理

```
GET  /api/alerts
GET  /api/alerts/stats
POST /api/alerts/{id}/ack
GET  /api/alerts/channels
POST /api/alerts/channels
POST /api/alerts/test
```

### 历史数据

```
GET  /api/history/probe_results
GET  /api/history/trends/ping?target=IP&hours=24
GET  /api/history/device_status
```

### 诊断

```
POST /api/diagnosis/diagnose
GET  /api/diagnosis/rules
GET  /api/diagnosis/quick/{agent_id}
```

### 排查向导

```
GET  /api/wizard/scenarios
POST /api/wizard/start?scenario_id=net_unreachable
POST /api/wizard/{session_id}/answer?response=...
```

### 故障传播

```
GET  /api/propagation/chain/{ip}
POST /api/propagation/root_cause
GET  /api/propagation/correlate
```

## 配置说明

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| SCKEY | Server酱 Key | - |
| DINGTALK_WEBHOOK | 钉钉机器人 Webhook | - |
| FEISHU_WEBHOOK | 飞书机器人 Webhook | - |
| ADMIN_PASSWORD | 管理密码 | admin |
| DATABASE_URL | 数据库路径 | ./monitor.db |
| CORS_ORIGINS | 允许的源（逗号分隔） | localhost |

## 技术栈

- 后端：FastAPI + APScheduler + SQLite
- 探测协议：ICMP / TCP / DNS / HTTP
- 前端：原生 HTML/CSS/JS + Chart.js
- 部署：Docker / docker-compose / Windows Service

## 项目结构

```
lanwatch_agent/
├── server/                 # 服务端
│   ├── main.py            # FastAPI 入口
│   ├── core/              # 核心模块（配置/数据库/认证）
│   ├── api/               # API 路由
│   ├── models/            # Pydantic 模型
│   ├── modules/           # 业务模块（探测/调度/告警/拓扑/诊断）
│   ├── templates/         # Web 前端
│   └── tests/             # pytest 测试
├── agent/
│   ├── windows/           # Windows Agent（打包入口 setup/build_spec.spec）
│   ├── linux/             # Linux Agent 源码（尚无安装包）
│   ├── mac/               # macOS Agent 源码（尚无安装包）
│   └── router/            # OpenWrt 路由器 Agent 源码（尚无安装包）
├── docker-compose.yml     # Docker 部署
├── Dockerfile
└── README.md
```

## License

MIT
