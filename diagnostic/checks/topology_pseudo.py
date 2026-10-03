"""
topology_pseudo.py — 组网结构检测伪代码

⚠️ SOP 细化用的伪代码，不是 v1.0 最终实现

最终实现路径（v1.0）：
    lanwatch_diagnostic/checks/topology.py

参考决策树：docs/checks/topology.md

⚠️ 设计要点：
- 唯一不依赖原始抓包的 check（基于 traceroute + 路由表 + DNS 配置）
- 与其他 3 个 check 并发跑，不抢资源
- 维度 B（网关不在子网）是 CRITICAL 强信号
"""

import sys
sys.path.insert(0, ".")
from rogue_router_pseudo import (
    Verdict, Confidence, SubFinding, EvidenceItem, CheckResult, DiagContext,
)


# ============================================================
# 内网段白名单（RFC1918 + CGNAT）
# ============================================================

import ipaddress

PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT，越来越多家用宽带
]

ABNORMAL_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local，APIPA
    ipaddress.ip_network("224.0.0.0/4"),     # multicast
    ipaddress.ip_network("240.0.0.0/4"),     # reserved
]


def _is_private_ip(ip: str) -> bool:
    """判断 IP 是否在内网段"""
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in PRIVATE_NETWORKS)
    except ValueError:
        return False


def _is_abnormal_ip(ip: str) -> bool:
    """判断 IP 是否在异常段"""
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in ABNORMAL_NETWORKS)
    except ValueError:
        return False


# ============================================================
# 主入口
# ============================================================

def check_topology(ctx: DiagContext) -> CheckResult:
    """
    组网结构检测

    4 个判断维度（详见 docs/checks/topology.md）：
      A: 公网跳数（traceroute）
      B: 默认网关是否在同子网（强信号）
      C: DNS 服务器位置
      D: 路由表异常

    不依赖原始抓包，可与其他 check 并发跑
    """
    # ── Phase 1: 数据采集 ────────────────────────────────
    traceroute_result = _traceroute(target="8.8.8.8", max_hops=15, timeout=3)
    fallback_traceroute = _traceroute(target="114.114.114.114", max_hops=15, timeout=3)
    # 取跳数最多的作为最差值
    max_hop_count = max(
        len(traceroute_result) if traceroute_result else 0,
        len(fallback_traceroute) if fallback_traceroute else 0,
    )

    local_subnet = _calc_subnet(ctx.local_ip, _get_local_mask(ctx.iface))
    dns_servers = _get_dns_servers(ctx.iface)
    routes = _get_routing_table()  # [(dest, gateway, mask, metric, iface), ...]

    # ── Phase 2: 4 个子判断 ──────────────────────────────
    sub_findings = [
        _check_traceroute_hops(max_hop_count),
        _check_gateway_subnet_match(ctx.gateway_ip, local_subnet),
        _check_dns_server_location(dns_servers),
        _check_routing_table(routes),
    ]

    # ── Phase 3: 综合判定 ────────────────────────────────
    verdict, confidence, summary = _synthesize_verdict(sub_findings)

    # ── Phase 4: 证据 + 话术 ─────────────────────────────
    evidence = _build_evidence(
        ctx, local_subnet, traceroute_result, dns_servers, routes, sub_findings
    )
    remediation, questions = _build_onsite_playbook(verdict, sub_findings)

    return CheckResult(
        name="topology",
        verdict=verdict,
        confidence=confidence,
        summary=summary,
        sub_findings=sub_findings,
        evidence=evidence,
        remediation=remediation,
        onsite_questions=questions,
    )


# ============================================================
# Phase 1 — 数据采集
# ============================================================

def _traceroute(target: str, max_hops: int = 15, timeout: int = 3) -> list[dict]:
    """
    Traceroute 到目标

    返回: [{"hop": 1, "ip": "192.168.1.1", "rtt_ms": 1.2}, ...]

    TODO: 用 scapy 发 UDP 包 + sniff ICMP TTL Exceeded
          或者 fallback: subprocess.run(["traceroute", "-m", str(max_hops), target])
    """
    # TODO: 真实实现
    return []


def _get_local_mask(iface: str) -> str:
    """读取本机接口的子网掩码，返回 CIDR 格式如 '/24'"""
    # TODO: psutil.net_if_addrs()[iface].netmask
    #       转成 ipaddress.IPv4Network 的 prefixlen
    return "/24"  # placeholder


def _calc_subnet(ip: str, mask: str) -> str:
    """
    计算子网 CIDR，如 "192.168.1.0/24"

    TODO: ipaddress.IPv4Network(f"{ip}{mask}", strict=False)
    """
    return ""


def _get_dns_servers(iface: str) -> list[str]:
    """
    读取本机 DNS 服务器列表

    TODO: Linux/macOS: 读 /etc/resolv.conf
          Windows: subprocess.run(["ipconfig", "/all"]) 解析
    """
    return []


def _get_routing_table() -> list[tuple]:
    """
    读取本机路由表

    返回: [(dest, gateway, mask, metric, iface), ...]

    TODO: Linux: 读 /proc/net/route
          macOS: subprocess.run(["netstat", "-rn"])
          Windows: subprocess.run(["route", "print"])
    """
    return []


# ============================================================
# Phase 2 — 4 个子判断
# ============================================================

def _check_traceroute_hops(hop_count: int) -> SubFinding:
    """维度 A: 公网跳数"""
    if hop_count > 10:
        v = Verdict.WARNING
    elif hop_count > 5:
        v = Verdict.WARNING  # 多层企业网，正常但记录
    else:
        v = Verdict.NORMAL
    return SubFinding(
        dimension="traceroute_hops",
        verdict=v,
        raw_value=hop_count,
        note=f"到公网跳数 {hop_count}" + ("（异常绕路）" if hop_count > 10 else ("（多层企业网）" if hop_count > 5 else "")),
    )


def _check_gateway_subnet_match(gateway_ip: str, local_subnet_cidr: str) -> SubFinding:
    """维度 B: 网关是否在同子网（强信号）"""
    try:
        gw = ipaddress.ip_address(gateway_ip)
        subnet = ipaddress.ip_network(local_subnet_cidr, strict=False)
        in_subnet = gw in subnet
    except (ValueError, TypeError):
        return SubFinding(
            dimension="gateway_subnet",
            verdict=Verdict.NORMAL,  # 信息不足不报警
            raw_value=None,
            note="无法判定（数据缺失）",
        )

    if in_subnet:
        v = Verdict.NORMAL
    else:
        v = Verdict.CRITICAL  # 强信号

    return SubFinding(
        dimension="gateway_subnet",
        verdict=v,
        raw_value={"gateway_ip": gateway_ip, "subnet": local_subnet_cidr, "in_subnet": in_subnet},
        note=f"网关 {gateway_ip} {'在' if in_subnet else '不在'} {local_subnet_cidr} 内" + ("（拓扑错配）" if not in_subnet else ""),
    )


def _check_dns_server_location(dns_servers: list[str]) -> SubFinding:
    """维度 C: DNS 服务器位置"""
    if not dns_servers:
        return SubFinding(
            dimension="dns_location",
            verdict=Verdict.WARNING,  # 没配 DNS 是异常
            raw_value=[],
            note="本机未配置 DNS 服务器",
        )

    locations = []
    worst_verdict = Verdict.NORMAL

    for dns in dns_servers:
        if _is_abnormal_ip(dns):
            locations.append({"ip": dns, "location": "abnormal"})
            worst_verdict = Verdict.CRITICAL
        elif _is_private_ip(dns):
            locations.append({"ip": dns, "location": "private"})
            # private 正常
        else:
            locations.append({"ip": dns, "location": "public"})
            if worst_verdict != Verdict.CRITICAL:
                worst_verdict = Verdict.WARNING

    return SubFinding(
        dimension="dns_location",
        verdict=worst_verdict,
        raw_value=locations,
        note=f"DNS 服务器: {', '.join(d['ip'] + '(' + d['location'] + ')' for d in locations)}",
    )


def _check_routing_table(routes: list[tuple]) -> SubFinding:
    """维度 D: 路由表异常"""
    # routes: [(dest, gateway, mask, metric, iface), ...]
    default_routes = [r for r in routes if r[0] == "0.0.0.0"]

    if not default_routes:
        return SubFinding(
            dimension="routing_table",
            verdict=Verdict.CRITICAL,
            raw_value=[],
            note="无默认路由（无法上外网）",
        )

    if len(default_routes) >= 2:
        metrics = [r[3] for r in default_routes]
        # metric 接近 → 负载均衡；差异大 → 错配
        if max(metrics) - min(metrics) > 10:
            return SubFinding(
                dimension="routing_table",
                verdict=Verdict.WARNING,
                raw_value=default_routes,
                note=f"{len(default_routes)} 条默认路由，metric 差异大（{min(metrics)}~{max(metrics)}），疑似错配",
            )
        else:
            return SubFinding(
                dimension="routing_table",
                verdict=Verdict.WARNING,
                raw_value=default_routes,
                note=f"{len(default_routes)} 条默认路由（负载均衡，正常）",
            )

    return SubFinding(
        dimension="routing_table",
        verdict=Verdict.NORMAL,
        raw_value=default_routes,
        note=f"{len(default_routes)} 条默认路由（正常）",
    )


# ============================================================
# Phase 3 — 综合判定
# ============================================================

def _synthesize_verdict(sub_findings: list[SubFinding]) -> tuple[Verdict, Confidence, str]:
    """按 docs/checks/topology.md §三 的决策树综合判定"""
    by_dim = {f.dimension: f for f in sub_findings}
    a = by_dim["traceroute_hops"].verdict
    b = by_dim["gateway_subnet"].verdict
    c = by_dim["dns_location"].verdict
    d = by_dim["routing_table"].verdict

    # 强信号：网关不在子网 OR 无默认路由
    if b == Verdict.CRITICAL or d == Verdict.CRITICAL:
        return (
            Verdict.CRITICAL,
            Confidence.HIGH,
            "强证据显示拓扑严重错配（网关或路由配置错误）",
        )

    # 中信号：DNS 异常 OR 多路由错配
    if c in (Verdict.WARNING, Verdict.CRITICAL) or d == Verdict.WARNING:
        return (
            Verdict.WARNING,
            Confidence.MEDIUM,
            "检测到 DNS 或路由表异常，建议现场确认",
        )

    # 弱信号：跳数过多
    if a == Verdict.WARNING:
        return (
            Verdict.WARNING,
            Confidence.LOW,
            "公网跳数较多，建议检查路由策略",
        )

    return (
        Verdict.NORMAL,
        Confidence.HIGH,
        "组网结构正常，未检测到错配迹象",
    )


# ============================================================
# Phase 4 — 证据 + 话术
# ============================================================

def _build_evidence(
    ctx: DiagContext,
    local_subnet: str,
    traceroute: list[dict],
    dns_servers: list[str],
    routes: list[tuple],
    sub_findings: list[SubFinding],
) -> list[EvidenceItem]:
    evidence = []
    by_dim = {f.dimension: f for f in sub_findings}

    # 网关不在子网（最严重的证据）
    if by_dim["gateway_subnet"].verdict == Verdict.CRITICAL:
        evidence.append(EvidenceItem(
            type="subnet_mismatch",
            title="默认网关不在本机子网",
            items=[
                {"local_ip": ctx.local_ip, "local_subnet": local_subnet},
                {"gateway_ip": ctx.gateway_ip, "note": "不在本机子网内"},
            ],
        ))

    # 路由表（无默认路由）
    if by_dim["routing_table"].verdict == Verdict.CRITICAL:
        evidence.append(EvidenceItem(
            type="no_default_route",
            title="无默认路由",
            items=[],
        ))

    # Traceroute 路径
    if traceroute:
        evidence.append(EvidenceItem(
            type="traceroute",
            title=f"到 8.8.8.8 的路径（共 {len(traceroute)} 跳）",
            items=traceroute,
        ))

    # DNS 配置
    if dns_servers:
        evidence.append(EvidenceItem(
            type="dns_config",
            title="本机 DNS 配置",
            items=[
                {
                    "dns_ip": s,
                    "location": "abnormal" if _is_abnormal_ip(s) else ("private" if _is_private_ip(s) else "public"),
                }
                for s in dns_servers
            ],
        ))

    return evidence


def _build_onsite_playbook(verdict: Verdict, sub_findings: list[SubFinding]) -> tuple[list[str], list[str]]:
    if verdict == Verdict.CRITICAL:
        return (
            [
                "立即修正默认网关配置（检查路由器 LAN 口 IP）",
                "若客户多网卡场景可忽略 → 现场确认",
                "推荐方案：装 lanwatch_agent 持续监控，自动告警拓扑变化",
            ],
            [
                "客户问'网络有问题吗'：是'有强证据显示默认网关配错了，可能完全无法访问外网'",
            ],
        )
    if verdict == Verdict.WARNING:
        return (
            [
                "检查路由器路由表（可能 metric 配错）",
                "检查 DNS 配置（若客户主动指向公网可忽略）",
                "推荐方案：装 lanwatch_agent 持续监控",
            ],
            [
                "问客户：'你们有几个外网出口？是否做了多网卡负载均衡？'",
                "问客户：'DNS 服务器是客户主动配的还是默认 DHCP 派发的？'",
            ],
        )
    return (
        [
            "组网结构正常",
            "建议定期用 lanwatch_agent 自动巡检拓扑变化",
        ],
        [],
    )


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    test_cases = [
        # 1. CRITICAL：网关不在子网
        [
            SubFinding("traceroute_hops", Verdict.NORMAL, 4, ""),
            SubFinding("gateway_subnet", Verdict.CRITICAL, {"in_subnet": False}, ""),
            SubFinding("dns_location", Verdict.NORMAL, [], ""),
            SubFinding("routing_table", Verdict.NORMAL, [], ""),
        ],
        # 2. WARNING：DNS 指向公网 + 多路由
        [
            SubFinding("traceroute_hops", Verdict.NORMAL, 3, ""),
            SubFinding("gateway_subnet", Verdict.NORMAL, {"in_subnet": True}, ""),
            SubFinding("dns_location", Verdict.WARNING, [{"ip": "8.8.8.8", "location": "public"}], ""),
            SubFinding("routing_table", Verdict.WARNING, [], ""),
        ],
        # 3. NORMAL：全绿
        [
            SubFinding("traceroute_hops", Verdict.NORMAL, 4, ""),
            SubFinding("gateway_subnet", Verdict.NORMAL, {"in_subnet": True}, ""),
            SubFinding("dns_location", Verdict.NORMAL, [{"ip": "192.168.1.1", "location": "private"}], ""),
            SubFinding("routing_table", Verdict.NORMAL, [], ""),
        ],
        # 4. 弱信号 WARNING：仅跳数过多
        [
            SubFinding("traceroute_hops", Verdict.WARNING, 14, ""),
            SubFinding("gateway_subnet", Verdict.NORMAL, {"in_subnet": True}, ""),
            SubFinding("dns_location", Verdict.NORMAL, [], ""),
            SubFinding("routing_table", Verdict.NORMAL, [], ""),
        ],
    ]

    expected = ["critical/high", "warning/medium", "normal/high", "warning/low"]
    for i, (findings, exp) in enumerate(zip(test_cases, expected)):
        v, c, s = _synthesize_verdict(findings)
        print(f"[Test {i+1}] {v.value}/{c.value} — 预期 {exp} | 摘要: {s}")