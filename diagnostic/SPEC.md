# Lanwatch Diagnostic — 上门成交加速器

> 子项目：lanwatch_agent / diagnostic
> 文档状态：Draft v0.2（算法决策已 Locked，可进 MVP 开发）
> 最后更新：2026-09-23（22:19 — Q1-4 拍板 + 新增 P2P/BT 检测）

---

## 一、Why — 为什么做这个

### 1.1 一句话定位

**这玩意儿不是诊断器，是上门成单加速器。**

找 4 类网络问题只是表层动作，真正的价值链是：

> 工程师带 U 盘到客户现场 → 5 分钟内让客户亲眼看见证据 → 客户从"我们网络没事"变成"卧槽真有事" → 自然接受 SaaS 托管 → 成交

### 1.2 三股力量在 2026-09-23 这个时点合流

| 力量 | 现状 | 缺口 |
|------|------|------|
| **超哥 20 年弱电经验** | 见过私接小路由、环路、ARP 欺骗、组网乱搞的所有"丑陋现场"，脑子里有判断 SOP | 没有工具化，每次上门都用脑子 + 眼睛，累且不可复制 |
| **lanwatch_agent 主项目** | Server / Agent / 拓扑 / 告警 / 诊断 / 数字分身 都已 ready | **缺一个"上门钩子"**：潜在客户没遇到事不会主动买，遇到了我们又不能第一时间到现场 |
| **市场窗口** | 中小企业老板对"网络偶尔卡"已经麻木 | 缺一个**可视化证据**——光说"你网络有问题"没人信，**亲眼看见封包/ARP/环路证据**才会买单 |

### 1.3 我们不做什么（明确范围）

- ❌ 不替代 nmap / Wireshark / 商用网管——他们是给网络工程师用的，我们是给**销售场景**用的
- ❌ 不做持续监控——那是 lanwatch_agent SaaS 自己的事
- ❌ 不远程诊断——必须在客户现场，本机接入网络才能跑
- ❌ 不修电脑、不杀病毒、不改拓扑——只**确认有没有问题 + 出具可视化报告**

---

## 二、What — 产品定位

### 2.1 它是什么

一个**单文件可运行的 Python CLI 工具**，插到客户内网任意一台笔记本上，一行命令 5 分钟出报告：

```bash
# 超哥（或同行弱电工程师）到客户现场后
lanwatch-diag run \
  --company "某某科技公司" \
  --contact "王总 138xxxx" \
  --server https://lanwatch.example.com
```

输出：
1. **现场打印的 HTML 报告**（带可视化证据，普通人能看懂）
2. **后台静默上传到 lanwatch_agent Server**（形成数字分身素材 + 销售漏斗）

### 2.2 它不是什么

| ✗ 不是 | ✓ 是 |
|--------|------|
| 通用网络诊断器 | 销售场景专用工具 |
| 给网管用的工具 | 给"不懂网络但要看证据的人"用的工具 |
| 替代持续监控 | "上门一次确诊"的事后补位 |
| 需要安装的复杂产品 | U 盘即插即跑的绿色工具 |

### 2.3 名字 & 调性

- 包名：`lanwatch-diagnostic`
- CLI 命令：`lanwatch-diag`
- 调性：**像法医现场取证**，不炫耀技术，让证据自己说话

---

## 三、For Whom — 谁会用

### 3.1 三类用户

| 角色 | 痛点 | 我们怎么帮 |
|------|------|-----------|
| **超哥本人** | 上门要快速让客户信服 | 5 分钟 SOP + 可视化证据 + 自动归档 |
| **同行弱电工程师**（同行渠道） | 自己有技术但缺"客户视角的呈现工具" | 工具白标可用，自己出报告，自己收费 |
| **渠道伙伴 / 销售** | 完全不懂网络，但需要工具开局 | 图形化向导 + 话术提示，照着做不犯错 |

### 3.2 客户画像

- 中小企业 30-200 人办公室，老板或 IT 负责人被"网络偶尔出问题"困扰
- 当前没有网管系统，或用了但没出过大问题所以没续费
- **关键心态**：对"网络有问题"半信半疑，必须**亲眼看到证据**才愿意掏钱

---

## 四、How — 5 分钟 SOP + 4 类问题

### 4.1 现场 5 分钟 SOP

```
T+0:00  到场。笔记本插客户内网任意网口，连上 WiFi 也行
T+0:30  打开终端 → lanwatch-diag run --company "..." --contact "..."
T+1:00  工具开始自动跑（4 个 check 并发）
T+3:30  跑完，自动出 HTML 报告
T+4:00  把报告页面打开给客户看——指着证据讲"您看，第 X 项就是您的问题"
T+4:30  引导到 lanwatch_agent SaaS（"装了我们这个，您就不用每次我上门了"）
T+5:00  收单 / 约下次 / 留资料，三选一
```

### 4.2 4 类问题检测逻辑（**按现场发生频率排**）

#### Check 1：私接小路由（Rogue Router）

**判断逻辑**：
1. 抓本机 ARP 表，记录所有网关候选 IP 的 MAC
2. 用 scapy 向网段发 ARP 请求，扫描所有存活主机的 MAC
3. **关键启发式**：
   - 同一网段出现 ≥2 个"声称是网关"的 MAC → 私接
   - 出现非 Cisco/Huawei/Ruijie 等主流厂商 MAC 前缀的设备在响应 ARP → 可疑
   - DHCP Discover 看返回的 Option 54（Server Identifier）数量 > 1 → 多 DHCP
4. **证据呈现**：列出所有"声称是网关"的 IP+MAC+厂商，让客户自己看哪个不该出现

#### Check 2：病毒 / 恶意软件（Malware / 挖矿 / C2 上传）⭐ **重灾区**

> **覆盖范围**：挖矿木马（半夜上传/连接矿池）/ C2 上传（中毒设备外发数据）/ DNS 隧道（隐蔽通道）/ 内网扫描（蠕虫横向移动）

**判断逻辑**：
1. 抓 60 秒内本机看到的**所有 TCP/UDP 连接**（按进程聚合）
2. 用 psutil 拿**每个进程的网络连接 + CPU/内存占用**
3. **关键启发式**：
   - 某进程**半夜**仍维持大量上行连接 → 挖矿 / C2
   - 连接到**已知矿池端口**（3333 / 14444 / 14433 / 7777 / 8888）或**已知 C2 端口** → 可疑
   - 单台设备**DNS 查询量**远高于其他设备 → DNS 隧道
   - 进程名是**伪装系统服务**（svch0st.exe / csrs.exe） → 可疑
   - 短时间内对**多个不同 IP 发起连接** → 蠕虫扫描
4. **证据呈现**：
   - **Top 10 进程**按上行流量排名 + 远端 IP 列表
   - **可疑进程**单独标记，给出**为什么可疑**（人话版）
   - 时间线：哪 10 秒上传最多 / 哪个 IP 被访问最多

#### Check 3：网络环路（Loop / Broadcast Storm）

**判断逻辑**：
1. 抓 30 秒内广播包数量（`scapy.sniff(filter="ether broadcast"...)`）
2. 统计每秒广播包速率
3. **阈值**：
   - 正常：< 50 pps
   - 警告：50-500 pps
   - 确认环路：> 500 pps 或 MAC 地址表漂移（同一 MAC 出现在多个端口）
4. **证据呈现**：实时广播包速率折线图 + 抓到的环路 STP BPDU 包样本

#### Check 4：组网结构问题（Topology Issues）

**判断逻辑**：
1. 主动 traceroute 到公网 + 内网网关 + 内网 DNS
2. 抓本机路由表（`netstat -rn` / `ip route`）
3. **关键启发式**：
   - traceroute 跳数异常多（> 10 跳到 8.8.8.8）→ 路由绕路
   - 出现本机子网之外的 IP 在响应 ARP → VLAN / 子网划分错
   - DNS 服务器响应 IP 不在常见内网段 → DNS 被劫持或配错
   - 默认网关不在本机子网内 → 拓扑错误
4. **证据呈现**：traceroute 路径图 + 异常项清单

### 4.3 报告输出规范

**HTML 报告分四段**：

```
┌─────────────────────────────────────┐
│ [Header] 公司名 / 时间 / 联系人       │
│ [总评] 一句话：建议 / 警告 / 正常      │
├─────────────────────────────────────┤
│ [Check 1] 私接小路由 → 图+证据列表   │
│ [Check 2] 环路 → 速率图+证据         │
│ [Check 3] ARP 欺骗 → 时间线+证据     │
│ [Check 4] 组网 → traceroute 图+证据  │
├─────────────────────────────────────┤
│ [下一步] 安装 lanwatch_agent SaaS   │
│          → 扫码 / 留资料 / 约演示    │
└─────────────────────────────────────┘
```

**调性**：像医院体检报告——客户看不懂代码没关系，看图、看红绿、看箭头。

---

## 四·四、算法决策表（v0.2 Locked）

> 2026-09-23 超哥拍板的 13 个决策 + P2P/BT 检测增强——**MVP 开发直接照此落地**。

### Check 1：rogue_router（已锁）
- **Q1.1 私接判定**：永远 strict——多个 DHCP/多网关一律 `critical`（**宁误勿漏**）
- **Q1.2 DHCP Discover 超时**：**5 秒**
- **Q1.3 ARP 扫描子网**：从本机网关推（自适应 `/24`–`/22`）

### Check 2：malware + 带宽异常（**重灾区**已锁）
- **Q2.1 矿池端口列表**：**内置 + 拉开源威胁情报**（VirusTotal / abuse.ch / etc.）
  - **内置**：[3333, 14444, 14433, 7777, 8888, 9999, 443（high-volume）]
  - **增量更新**：v1.0 从 server 拉（agent_id 复用 diagnostic）
- **Q2.2 "员工挖矿"误报处理**：warning + 备注**"可能是员工主动行为"**——不直接标 critical，留现场判断空间
- **Q2.3 DNS 监听**：只看 `53/UDP`（DoH 太复杂，v1.0 不做）
- **Q2.4 进程白名单**：内置静态（首版够用），server 增量 v2.0

#### 🆕 P2P / BT 下载检测（**超哥新增**）

> **不是恶意软件，但带宽是真杀手**——**P2P/BT 是"网速慢"的常见隐形原因**。

| 信号 | 详情 |
|------|------|
| **进程名清单** | `uTorrent` / `qBittorrent` / `Transmission` / `Deluge` / `Vuze` / `eMule` / `eMuleX` / `BitComet` / `Thunder`（迅雷）/ `FrostWire` / `Shareaza` / `Ares` / `BitLord` |
| **端口范围** | `6881–6889`（BitTorrent 默认）/ `2710`（eMule）/ `16881`（WinMX）/ `51413`（Transmission）/ `6881-6889` 高位段 |
| **连接模式** | 单进程 30 秒内 `distinct remote IP > 50` → P2P 嫌疑 |
| **DNS 特征** | 查询 `.torrent` / `tracker.*` / `*.bt.` 域名 |
| **判定级别** | `warning`（**不是 critical** —— 是带宽问题，不是安全问题）|

**False positive 警示**（写进 `verdict.py` 备注）：
- 企业 P2P 内部分发（合法用）
- VPN 客户端（多连接易混淆）
- 云盘同步（OneDrive / Dropbox / 坚果云）
- 浏览器开多个 tab 加载图片/视频

### Check 3：loop（已锁）
- **Q3.1 阈值**：默认 `50 / 500 pps`（正常/警告/确认），跑几次现场再校准
- **Q3.2 交换机不可达**：**只跑 pps 检测**，不跳过整个 check
- **Q3.3 BPDU 抓到 ≠ 一定没事**：BPDU + pps 联合判断（pps 是硬指标）

### Check 4：topology（已锁）
- **Q4.1 traceroute 超时**：**3s/跳，最多 8 跳**
- **Q4.2 Windows 适配**：用 Python 库自己发（scapy.layers.inet），**跨平台一致**，不调系统 tracert
- **Q4.3 内网 DNS 识别**：`resolv.conf` + 探测常见 DNS 端口（**二者结合**）

### 跨 check 共性（已锁）
- **scapy 需要 sudo**：CLI 启动检测 + 友好提示
- **抓包超时**：每个 sniff **30s hard timeout**
- **现场没网**：upload 重试 + 离线队列（已写进 §6.3）
- **测试数据**：超哥需提供 2–3 个真实客户网络的匿名化样本（pcap / ARP 表），**MVP 校准必须**

---

## 五、Tech — 技术栈

### 5.1 选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 语言 | **Python 3.12+** | 超哥熟、跨平台、scapy 生态好 |
| 原始包 | **scapy** | ARP / DHCP / 广播抓包一把抓，业内事实标准 |
| 系统信息 | **psutil** | 跨平台读 ARP 表 / 路由表 / 接口信息 |
| CLI | **click** | 超哥熟，文档好，扩展性强 |
| 报告模板 | **Jinja2** | HTML 模板写起来直观 |
| 图表 | **Chart.js**（前端） | 报告 HTML 里画广播速率折线图，轻量 |
| HTTP 上传 | **httpx** | 同步异步都支持，超时控制好 |
| 打包 | **PyInstaller** | 出单文件 exe（Windows 现场最方便） |

### 5.2 参考 LocalNet Explorer 的 ARP 思路

不重复造轮子。LocalNet Explorer 是个成熟的开源工具：
- 仓库：https://github.com/scls19fr/localnet-explorer
- 它用 scapy 做 ARP 扫描、DHCP 发现、端口发现
- **我们直接借鉴它的 ARP 扫描模块**（MIT 协议），把"展示"层重写成我们的销售场景模板

### 5.3 目录结构（v1.0）

```
lanwatch_agent/
└── diagnostic/                          ← 本子项目
    ├── SPEC.md                          ← 本文件
    ├── README.md                        ← 给同行用的快上手
    ├── pyproject.toml                   ← 依赖声明
    ├── lanwatch_diagnostic/
    │   ├── __init__.py
    │   ├── __main__.py                  ← python -m lanwatch_diagnostic
    │   ├── cli.py                       ← click 入口
    │   ├── runner.py                    ← 5 分钟编排 + 并发调度
    │   ├── checks/
    │   │   ├── __init__.py
    │   │   ├── rogue_router.py          ← Check 1
    │   │   ├── malware.py               ← Check 2（病毒 / 恶意软件）
    │   │   ├── loop.py                  ← Check 3（环路 / Broadcast Storm）
    │   │   └── topology.py              ← Check 4
    │   ├── collectors/
    │   │   ├── arp_table.py             ← 本机 ARP 表
    │   │   ├── arp_scan.py              ← 主动 ARP 扫描
    │   │   ├── dhcp_probe.py            ← DHCP 服务器发现
    │   │   ├── sniff.py                 ← 流量采样
    │   │   └── traceroute.py            ← 路径追踪
    │   ├── report/
    │   │   ├── html.py                  ← Jinja2 渲染
    │   │   ├── templates/
    │   │   │   └── report.html.j2
    │   │   └── static/
    │   │       └── chart.min.js         ← 图表库（本地内嵌）
    │   └── upload/
    │       └── server_client.py         ← httpx 上传
    └── tests/
        ├── test_rogue_router.py
        ├── test_loop.py
        ├── test_arp_spoof.py
        └── fixtures/                    ← 抓包样本（pcap）回归测试
```

---

## 六、Integration — 跟 lanwatch_agent 闭环

### 6.1 上传什么

报告 JSON（除了 HTML 给人看的）：

```json
{
  "site_info": {
    "company": "某某科技公司",
    "contact": "王总 13800000000",
    "engineer": "超哥",
    "started_at": "2026-09-23T14:00:00+08:00",
    "finished_at": "2026-09-23T14:05:23+08:00"
  },
  "summary": {
    "verdict": "warning",           // normal / warning / critical
    "score": 65,                    // 0-100 健康分
    "top_issues": ["rogue_router", "loop"]
  },
  "checks": {
    "rogue_router": { "verdict": "critical", "evidence": [...] },
    "malware":      { "verdict": "warning",  "evidence": [...] },
    "loop":         { "verdict": "normal",   "evidence": [] },
    "topology":     { "verdict": "warning",  "evidence": [...] }
  },
  "recommendation": {
    "lanwatch_agent_plan": "standard",       // basic / standard / pro
    "reason": "检测到 1 个私接路由 + 1 个广播风暴，建议托管监控"
  }
}
```

### 6.2 上传到哪儿

**复用现有 Server API**——主项目已经有 `POST /api/{agent_id}/diag`（来自 server/README.md + server/core/database.py 已存在 `diag_reports` 表），**直接对接，不要新建表/路由**。

```python
# upload/server_client.py
async def upload(server_url: str, agent_id: str, report: dict):
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{server_url}/api/{agent_id}/diag",
            headers={"X-Diagnostic-Source": "lanwatch-diag/0.1"},
            json=report,
        )
        r.raise_for_status()
```

**agent_id 怎么定**（**对齐决策**）：

| 阶段 | 方案 |
|------|------|
| **MVP** | CLI 加 `--agent-id` 参数，默认 `diagnostic`，超哥和首批试用者**复用同一个** |
| **v1.0** | 每个工程师**注册**自己的 agent_id（一次命令 `lanwatch-diag register --name "超哥"`），后续报告按人归档 |
| **v2.0** | 多租户鉴权 + 现场临时一次性 token（参见附录 B） |

> ⚠️ **MVP 阶段必须先用这个 agent_id 去 server 注册**，否则 server 会拒收——这一步跟主项目那边的 schema 对齐是**这次 SPEC review 的核心**。

### 6.3 上传失败怎么办

- **不阻塞现场流程**——上传是后台任务，本地 HTML 报告必须先出来
- 失败重试 3 次（指数退避），最终失败写本地 `~/.lanwatch_diag/queue/` 等下次联网补传
- 现场 5 分钟黄金窗口 > 数据完整性，先成交再说

### 6.4 Server 端配套改动（**最小化**）

**复用主项目已有 schema**，**不新增表**：

```sql
-- 主项目已有表（server/core/database.py）:
CREATE TABLE IF NOT EXISTS diag_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**只需要**：
1. 现有 `diag_reports.report_json` 字段**够装我们的全量 JSON**——**够**（JSON 文本存什么都行）
2. 加个**管理后台视图** `server/modules/diagnostic_view.py`：按 agent_id + 公司 + 时间筛选历史报告
3. **不需要改 schema**——零迁移成本

> **这就是"闭环对齐"的具体动作**：不是新建表，是**把现有表用起来 + 加视图**。任何 schema 改动都要先跟主项目 owner（超哥）确认，避免多个 PR 撞车。

---

## 七、Success Metrics — 成功标准

### 7.1 MVP 阶段（内部可用）

| 指标 | 目标 | 测量方式 |
|------|------|---------|
| 5 分钟内出诊断 | ✅ 端到端 < 300s | 自动化计时测试 |
| 4 类 check 都跑通 | ✅ 不漏检 | 单测 + 集成测试 |
| HTML 报告能在断网环境打开 | ✅ 内嵌 CSS/JS | 离线运行测试 |
| Server 闭环上传成功率 | ≥ 95%（Server 可达时） | Server 端日志统计 |

### 7.2 上线阶段（验证商业模式）

| 指标 | 目标 | 测量方式 |
|------|------|---------|
| SOP 判断准确率 | ≥ 90%（人工 review 校准） | 超哥 + 同行工程师盲评 50 份报告 |
| **现场成单率** | 这是**最核心**指标 | 销售跟进：上门→签约转化率 |
| 同行复用率 | ≥ 30%（用过的同行愿意再用 / 推荐） | 渠道反馈 |

> 注：**现场成单率是这产品的命**，技术指标是手段不是目的。如果技术全绿但成单率上不去，要回头看是不是 SOP / 报告 / 话术有问题。

---

## 八、Roadmap — 三阶段路线

### 8.1 MVP（2 周内）— 内部验证想法

**目标**：超哥自己上门用一次，证明 5 分钟 SOP 可行 + 报告能让客户信服

**交付物**：
- 单文件 `diag.py`（不打包，~500 行）
- 4 个 check 各 ~30 行最简实现
- HTML 报告：纯文本表格 + 内嵌截图，**不要求好看**
- 不上传 Server，本地保存 HTML
- 跑在超哥自己笔记本上，macOS 优先

**不做**：
- 不打包 exe
- 不做单元测试
- 不做上传逻辑
- 不做白标

### 8.2 v1.0（4-6 周后）— 同行可用

**目标**：同行弱电工程师能直接用，开始小范围分发

**交付物**：
- Python 包结构（见 §5.3 目录）
- 单元测试覆盖 4 个 check 的核心判断逻辑
- Jinja2 报告模板，**比 MVP 好看 3 倍**
- CLI 完善：`--help` / `--output` / `--no-upload` / `--company` / `--contact`
- Server 闭环：上传 + 失败重试 + 离线队列
- PyInstaller 打 Windows exe
- Docker 镜像：`docker run lanwatch/diagnostic:latest`
- 写好 README.md（给同行快上手）

**不做**：
- 不做 GUI
- 不做 PDF
- 不做多语言
- 不做白标

### 8.3 v2.0（按需，2.0 起步）— 规模化

**目标**：渠道伙伴 / 销售能独立用，开始规模化铺

**交付物**：
- 可选 GUI（Electron 或 PyQt，看哪个熟）
- PDF 导出（用 weasyprint 或浏览器 headless 打印）
- 多语言（英文 / 繁体，预留东南亚）
- 品牌定制：logo / 颜色 / 公司名（白标）
- 手机扫码预览报告（Server 端生成短链）
- 报告模板可配置（不同行业 / 不同客户层级）

---

## 十、待超哥 Review 的关键决策

### Q1：4 类问题覆盖够不够？

**当前覆盖**（**超哥已调整**）：
- ✅ 私接小路由
- ⭐ **病毒 / 恶意软件**（挖矿、C2、DNS 隧道、蠕虫）—— **重灾区**
- ✅ 网络环路
- ✅ 组网结构

**可考虑加**：DNS 劫持、IP 冲突、交换机端口错配、WiFi 信道冲突

**我的建议**：v1.0 不加。先把 4 类做到 90% 准确率，再扩。**少即是多**。

### Q2：要不要做 Windows GUI（v1.0 就上）？

- 当前规划：v1.0 只做 CLI，v2.0 才上 GUI
- 反方观点：超哥现场用 macOS 没问题，但同行大多用 Windows，CLI 对他们门槛高

**我的倾向**：v1.0 出 exe + CLI（命令行可双击 .bat 脚本触发），GUI 留到 v2.0。

### Q3：报告里要不要直接放"lanwatch_agent 套餐报价"？

- **支持**：现场趁热打铁，转化率高
- **反对**：太商业化，像广告，会减分

**我的倾向**：放，但放得**克制**——报告末尾一栏"下一步建议"，让客户主动扫码看，不强推。

### Q4：要不要做成开源（MIT 同 lanwatch_agent）？

**✅ 超哥已决定：开源（MIT）**。原因：
1. 同行渠道用着放心，代码透明 = 信任何
2. 借鉴 LocalNet Explorer 是 MIT，不开源说不过去
3. lanwatch_agent 本身就是 MIT，子项目保持一致
4. 开源不阻挡商业化——SaaS 转化逻辑在 Server，不在 CLI
5. **verdict.py（4 类问题的判断逻辑）跟主代码一起开源**——超哥本人接受公开 SOP，因为 SOP 本身在客户现场可被模仿，**真正的护城河是"20 年经验 + 现场渠道 + SaaS 闭环"**，不是代码

---

## 附录 A：竞品 / 参考

| 工具 | 定位 | 我们差异化 |
|------|------|-----------|
| **LocalNet Explorer** | 开源 LAN 扫描器 | 它是给工程师用的，我们是给销售场景用的；报告层重写 |
| **nmap / Wireshark** | 专业网络分析 | 太专业，客户看不懂；我们出"人话"报告 |
| **SolarWinds / PRTG** | 商用网管 | 太贵、太重；我们轻、单次、不部署 |
| **同事带 U 盘装个工具** | 临时方案 | 不可复制、不可量化、不可规模化 |

## 附录 B：开放问题

- 5 分钟真的够吗？4 个 check 并发跑够不够？要不要先单线程跑一遍 estimate？
- 现场打印报告用什么方式？HTML 用浏览器打开？PDF 现场打？还是要做成单页 HTML 截图？
- 上传到 Server 需不需要鉴权？现场可能没带 API Key——可不可以现场临时生成一次性 token？

---

*SPEC 完。Next: 等超哥 review，意见落到本文件 §十 的开放问题里，然后决定是否进 MVP 开发。*