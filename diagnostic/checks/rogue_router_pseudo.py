"""
rogue_router_pseudo.py — 私接小路由检测伪代码

⚠️ 这是 SOP 细化用的伪代码，不是 v1.0 最终实现
- 函数签名已按 v1.0 提前定，方便后续直接实现
- TODO 标了实现细节，阈值/白名单都按 rogue_router.md 文档
- 实现时只需要把 # TODO 替换成真实 scapy/psutil 调用

最终实现路径（v1.0）：
    lanwatch_diagnostic/checks/rogue_router.py

参考决策树：docs/checks/rogue_router.md
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ============================================================
# 通用类型定义（v1.0 全部 checks 共享）
# ============================================================

class Verdict(str, Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class SubFinding:
    """单个维度的判定结果"""
    dimension: str           # "dhcp_count" | "gateway_mac" | "brand" | "drift"
    verdict: Verdict
    raw_value: any           # 原始信号值（数量、MAC 等）
    note: str = ""           # 解释


@dataclass
class EvidenceItem:
    """报告里的一条证据"""
    type: str                # "dhcp_servers" | "gateway_mac_collision" | ...
    title: str
    items: list[dict] = field(default_factory=list)


@dataclass
class CheckResult:
    """单个 check 的完整结果"""
    name: str
    verdict: Verdict
    confidence: Confidence
    summary: str
    sub_findings: list[SubFinding]
    evidence: list[EvidenceItem]
    remediation: list[str]
    # 给客户看的"现场提问话术"（超哥用）
    onsite_questions: list[str] = field(default_factory=list)


@dataclass
class DiagContext:
    """诊断上下文——本机接入内网后的环境信息"""
    iface: str               # 主接口名，如 "en0" / "eth0"
    local_ip: str            # 本机 IP，如 "192.168.1.100"
    cidr: str                # 子网，如 "192.168.1.0/24"
    gateway_ip: str          # 默认网关 IP
    mac: str                 # 本机 MAC


# ============================================================
# 主入口
# ============================================================

def check_rogue_router(ctx: DiagContext) -> CheckResult:
    """
    私接小路由检测

    综合 4 个维度（详见 docs/checks/rogue_router.md）：
      A: DHCP 服务器数量
      B: 声称是网关的 MAC 数量
      C: 未授权厂商（家用路由）的存活主机数
      D: 网关 MAC 时间稳定性

    返回 CheckResult，verdict/confidence 由综合判定决定
    """
    # ── Phase 1: 数据采集 ────────────────────────────────
    arp_table         = _collect_arp_table(ctx.iface)              # 本机 ARP 表
    dhcp_servers      = _discover_dhcp_servers(ctx.iface, timeout=5)  # DHCP probe
    subnet_alive      = _arp_scan_subnet(ctx.local_ip, ctx.cidr, timeout=30)
    gateway_history   = _monitor_gateway_mac(ctx.iface, ctx.gateway_ip, duration=10)

    # ── Phase 2: 4 个子判断 ──────────────────────────────
    sub_findings = [
        _check_dhcp_count(dhcp_servers),
        _check_gateway_mac_uniqueness(ctx.gateway_ip, arp_table, subnet_alive),
        _check_unauthorized_brands(subnet_alive),
        _check_gateway_mac_drift(gateway_history),
    ]

    # ── Phase 3: 综合判定 ────────────────────────────────
    verdict, confidence, summary = _synthesize_verdict(sub_findings)

    # ── Phase 4: 证据 + 现场话术 ─────────────────────────
    evidence = _build_evidence(dhcp_servers, subnet_alive, gateway_history, sub_findings)
    remediation, questions = _build_onsite_playbook(verdict, sub_findings)

    return CheckResult(
        name="rogue_router",
        verdict=verdict,
        confidence=confidence,
        summary=summary,
        sub_findings=sub_findings,
        evidence=evidence,
        remediation=remediation,
        onsite_questions=questions,
    )


# ============================================================
# Phase 1 — 数据采集（每个函数对应一个 scapy/psutil 实现）
# ============================================================

def _collect_arp_table(iface: str) -> dict[str, str]:
    """
    读取本机 ARP 表，返回 {ip: mac}

    TODO: 用 psutil.net_if_addrs() 拿接口信息 + psutil.net_connections()
          或者直接读 /proc/net/arp (Linux) / arp -a (macOS)
    """
    # TODO: 真实实现
    return {}  # placeholder


def _discover_dhcp_servers(iface: str, timeout: int = 5) -> list[dict]:
    """
    DHCP 探针：发 DHCP Discover，收 Offer，记录 Option 54（Server Identifier）

    返回: [
      {"server_ip": "192.168.1.1", "mac": "00:1A:2B:3C:4D:5E", "vendor": "TP-Link"},
      ...
    ]

    TODO: 用 scapy 发 Ether(src=<本机 MAC>, dst="ff:ff:ff:ff:ff:ff") / IP(src="0.0.0.0", dst="255.255.255.255") / UDP(sport=68, dport=67) / BOOTP(chaddr=[本机 MAC]) / DHCP(options=[("message-type","discover"),("end")])
          收 sniff(filter="udp and (port 67 or port 68)", timeout=5)
          解析 DHCP options 里的 Option 54
    """
    # TODO: 真实实现
    return []  # placeholder


def _arp_scan_subnet(local_ip: str, cidr: str, timeout: int = 30) -> list[dict]:
    """
    主动 ARP 扫描整个子网

    返回: [
      {"ip": "192.168.1.1", "mac": "00:1A:2B:3C:4D:5E", "vendor": "Cisco"},
      ...
    ]

    TODO: 解析 cidr 列出所有 IP（netaddr 模块），逐个 scapy.Ether(dst="ff:...)/ARP(pdst=ip) 发包
          收 sniff(filter="arp", timeout=...)，收集有响应的 IP/MAC
          查 OUI 前缀（自己维护一个 dict 或者用 netaddr.OUI）
    """
    # TODO: 真实实现
    return []  # placeholder


def _monitor_gateway_mac(iface: str, gateway_ip: str, duration: int = 10) -> list[str]:
    """
    持续采样网关 IP 的 ARP 响应 MAC，记录 MAC 序列

    返回: ["00:1A:2B:3C:4D:5E", "00:1A:2B:3C:4D:5E", "B0:4E:26:AA:BB:CC", "00:1A:2B:3C:4D:5E"]
         （变化次数 = 不同 MAC 的个数）

    TODO: 后台线程 / 协程，每秒发一次 ARP Request 给 gateway_ip，记录响应 MAC
          持续 duration 秒
    """
    # TODO: 真实实现
    return []  # placeholder


# ============================================================
# Phase 2 — 4 个子判断
# ============================================================

def _check_dhcp_count(dhcp_servers: list[dict]) -> SubFinding:
    """维度 A: DHCP 服务器数"""
    n = len(dhcp_servers)
    if n >= 3:
        v = Verdict.CRITICAL
    elif n == 2:
        v = Verdict.WARNING
    else:
        v = Verdict.NORMAL
    return SubFinding(
        dimension="dhcp_count",
        verdict=v,
        raw_value=n,
        note=f"发现 {n} 个 DHCP 服务器" + ("（含私接嫌疑）" if n >= 2 else ""),
    )


def _check_gateway_mac_uniqueness(
    gateway_ip: str,
    arp_table: dict[str, str],
    subnet_alive: list[dict],
) -> SubFinding:
    """维度 B: 声称是网关的 MAC 数"""
    gw_macs = set()

    # 从本机 ARP 表拿
    if gateway_ip in arp_table:
        gw_macs.add(arp_table[gateway_ip])

    # 从主动扫描结果拿——所有"声明自己是 gateway_ip"的 MAC（gratuitous ARP）
    for host in subnet_alive:
        if host.get("claimed_ip") == gateway_ip:    # TODO: 主动扫描里要带这个字段
            gw_macs.add(host["mac"])

    n = len(gw_macs)
    if n >= 3:
        v = Verdict.CRITICAL
    elif n == 2:
        v = Verdict.WARNING
    else:
        v = Verdict.NORMAL
    return SubFinding(
        dimension="gateway_mac",
        verdict=v,
        raw_value=sorted(gw_macs),
        note=f"网关 {gateway_ip} 被 {n} 个不同 MAC 声称" + ("（私接嫌疑）" if n >= 2 else ""),
    )


# 主流企业级厂商 OUI 前缀（白名单，节选，完整版在 implementation 里）
ENTERPRISE_OUI_WHITELIST = {
    "00:00:0C", "00:1A:A1", "00:1B:0D", "00:1D:A1", "00:22:55",  # Cisco
    "00:E0:FC", "00:25:9E", "00:F8:1C", "04:BD:70",                # Huawei
    "00:D0:F8", "58:69:6C",                                        # Ruijie
    "00:0F:E2",                                                    # H3C
    "00:1A:2E",                                                    # Aruba
    "24:5A:4C", "78:8A:20",                                        # Ubiquiti
    "00:0C:42",                                                    # Mikrotik
    "00:14:22",                                                    # Dell
    "00:08:02",                                                    # HP/HPE
    # ... 实施时补全
}

CONSUMER_BRAND_OUI = {
    "14:CC:20",  # TP-Link 部分
    "00:09:5B",  # Netgear
    "C8:3A:35",  # Tenda
    "00:1D:0F",  # Mercury 水星
    "90:FB:A6",  # Fast 迅捷
    "28:6C:07", "64:09:80",  # Xiaomi
    "BC:75:36",  # 360
    # ... 实施时补全
}


def _check_unauthorized_brands(subnet_alive: list[dict]) -> SubFinding:
    """维度 C: 未授权厂商（消费级路由）的存活主机数"""
    consumer_count = 0
    for host in subnet_alive:
        oui = host["mac"][:8].upper()  # 取 MAC 前 3 字节
        if oui in CONSUMER_BRAND_OUI and oui not in ENTERPRISE_OUI_WHITELIST:
            consumer_count += 1

    if consumer_count >= 10:
        v = Verdict.WARNING  # 这个维度最高只到 WARNING（见 SOP §四）
    else:
        v = Verdict.NORMAL
    return SubFinding(
        dimension="brand",
        verdict=v,
        raw_value=consumer_count,
        note=f"扫描到 {consumer_count} 个消费级路由厂商的设备",
    )


def _check_gateway_mac_drift(gateway_history: list[str]) -> SubFinding:
    """维度 D: 网关 MAC 时间稳定性"""
    distinct_macs = set(gateway_history)
    n = len(distinct_macs)
    if n >= 2:
        v = Verdict.WARNING
    else:
        v = Verdict.NORMAL
    return SubFinding(
        dimension="drift",
        verdict=v,
        raw_value=sorted(distinct_macs),
        note=f"10 秒内网关 MAC 变化 {n} 次" + ("（漂移/ARP 抢答）" if n >= 2 else ""),
    )


# ============================================================
# Phase 3 — 综合判定（决策树实现）
# ============================================================

def _synthesize_verdict(
    sub_findings: list[SubFinding],
) -> tuple[Verdict, Confidence, str]:
    """
    按 docs/checks/rogue_router.md §四 的决策树综合判定

    返回: (verdict, confidence, summary)
    """
    by_dim = {f.dimension: f for f in sub_findings}

    a = by_dim["dhcp_count"].verdict     # DHCP 数
    b = by_dim["gateway_mac"].verdict    # 网关 MAC 数
    c = by_dim["brand"].verdict          # 厂商数
    d = by_dim["drift"].verdict          # MAC 漂移

    # 双确认：CRITICAL
    if a in (Verdict.WARNING, Verdict.CRITICAL) and b in (Verdict.WARNING, Verdict.CRITICAL):
        return (
            Verdict.CRITICAL,
            Confidence.HIGH,
            "强证据双信号确认私接路由（DHCP + 网关冲突）",
        )

    # 单信号：WARNING
    if a in (Verdict.WARNING, Verdict.CRITICAL) or b in (Verdict.WARNING, Verdict.CRITICAL):
        return (
            Verdict.WARNING,
            Confidence.MEDIUM,
            "检测到单信号异常，建议现场排查",
        )

    # 弱信号：WARNING（低置信度）
    if c == Verdict.WARNING or d == Verdict.WARNING:
        return (
            Verdict.WARNING,
            Confidence.LOW,
            "检测到弱信号异常，需结合现场询问确认",
        )

    # 全部正常
    return (
        Verdict.NORMAL,
        Confidence.HIGH,
        "未检测到私接路由迹象",
    )


# ============================================================
# Phase 4 — 证据构建 + 现场话术
# ============================================================

def _build_evidence(
    dhcp_servers: list[dict],
    subnet_alive: list[dict],
    gateway_history: list[str],
    sub_findings: list[SubFinding],
) -> list[EvidenceItem]:
    """把原始数据组装成给 HTML 报告的 evidence 列表"""
    evidence = []

    # DHCP 服务器列表
    if len(dhcp_servers) >= 2:
        evidence.append(EvidenceItem(
            type="dhcp_servers",
            title=f"内网发现 {len(dhcp_servers)} 个 DHCP 服务器",
            items=[
                {"server_ip": s["server_ip"], "mac": s["mac"], "vendor": s.get("vendor", "?")}
                for s in dhcp_servers
            ],
        ))

    # 网关 MAC 冲突
    by_dim = {f.dimension: f for f in sub_findings}
    gw_macs = by_dim["gateway_mac"].raw_value
    if len(gw_macs) >= 2:
        evidence.append(EvidenceItem(
            type="gateway_mac_collision",
            title=f"网关被 {len(gw_macs)} 个不同 MAC 声称",
            items=[{"mac": m} for m in gw_macs],
        ))

    # 网关 MAC 漂移
    if by_dim["drift"].verdict != Verdict.NORMAL:
        evidence.append(EvidenceItem(
            type="gateway_mac_drift",
            title="网关 MAC 时间漂移",
            items=[{"mac_sequence": " → ".join(gateway_history)}],
        ))

    return evidence


def _build_onsite_playbook(
    verdict: Verdict,
    sub_findings: list[SubFinding],
) -> tuple[list[str], list[str]]:
    """
    生成报告里的"建议措施" + 给超哥的"现场话术/提问"

    返回: (remediation, onsite_questions)
    """
    remediation = []
    questions = []

    if verdict == Verdict.CRITICAL:
        remediation = [
            "立即在核心交换机上查 MAC 对应端口 → 定位私接设备",
            "拔除网线 → 通知员工/部门主管 → 收回路由",
            "推荐方案：装 lanwatch_agent 持续监控，自动告警此类事件",
        ]
        questions = [
            "客户问'我们网络有问题吗'：是'有强证据显示存在私接路由，建议立即排查'",
        ]
    elif verdict == Verdict.WARNING:
        remediation = [
            "现场询问客户是否有意部署多 DHCP / 多网关（合法双 ISP 冗余？DHCP relay？）",
            "若是合法部署 → 归档本次记录，无需处理",
            "若是私接 → 在交换机端口定位 → 拔线 → 通知",
            "推荐方案：装 lanwatch_agent 持续监控",
        ]
        questions = [
            "问客户：'你们有几个外网出口？是单线还是双 ISP 冗余？'",
            "问客户：'你们有多个 DHCP 服务器吗？或者做了 DHCP relay 中继？'",
        ]
    else:
        remediation = [
            "本次未发现私接路由迹象",
            "建议每月用 lanwatch_agent 自动巡检一次，主动发现隐患",
        ]
        questions = []

    return remediation, questions


# ============================================================
# 单元测试入口（v1.0 实现时补全）
# ============================================================

if __name__ == "__main__":
    # MVP 测试：用伪造的 sub_findings 跑综合判定，确认决策树对不对
    test_cases = [
        # 双信号 CRITICAL
        [
            SubFinding("dhcp_count", Verdict.WARNING, 2, ""),
            SubFinding("gateway_mac", Verdict.WARNING, ["m1", "m2"], ""),
            SubFinding("brand", Verdict.NORMAL, 3, ""),
            SubFinding("drift", Verdict.NORMAL, ["m1"], ""),
        ],
        # 全 NORMAL
        [
            SubFinding("dhcp_count", Verdict.NORMAL, 1, ""),
            SubFinding("gateway_mac", Verdict.NORMAL, ["m1"], ""),
            SubFinding("brand", Verdict.NORMAL, 2, ""),
            SubFinding("drift", Verdict.NORMAL, ["m1"], ""),
        ],
        # 弱信号 WARNING
        [
            SubFinding("dhcp_count", Verdict.NORMAL, 1, ""),
            SubFinding("gateway_mac", Verdict.NORMAL, ["m1"], ""),
            SubFinding("brand", Verdict.WARNING, 12, ""),
            SubFinding("drift", Verdict.NORMAL, ["m1"], ""),
        ],
    ]

    for i, findings in enumerate(test_cases):
        v, c, s = _synthesize_verdict(findings)
        print(f"[Test {i+1}] verdict={v.value}, confidence={c.value}, summary={s}")

    # 预期输出：
    # [Test 1] verdict=critical, confidence=high, summary=强证据双信号确认私接路由（DHCP + 网关冲突）
    # [Test 2] verdict=normal, confidence=high, summary=未检测到私接路由迹象
    # [Test 3] verdict=warning, confidence=low, summary=检测到弱信号异常，需结合现场询问确认