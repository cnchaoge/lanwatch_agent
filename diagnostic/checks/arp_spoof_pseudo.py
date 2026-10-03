"""
arp_spoof_pseudo.py — ARP 欺骗检测伪代码

⚠️ SOP 细化用的伪代码，不是 v1.0 最终实现

最终实现路径（v1.0）：
    lanwatch_diagnostic/checks/arp_spoof.py

参考决策树：docs/checks/arp_spoof.md

⚠️ 设计要点：
- 与 rogue_router 维度 D 共享 gateway_mac 历史（v1.0 抽到 common.collectors）
- 与 loop / rogue_router 共享 ARP 抓包（避免重复抓）
- 维度 D（攻击工具 OUI）v1 不实现
"""

import sys
sys.path.insert(0, ".")
from rogue_router_pseudo import (
    Verdict, Confidence, SubFinding, EvidenceItem, CheckResult, DiagContext,
)


# ============================================================
# 主入口
# ============================================================

def check_arp_spoof(ctx: DiagContext, shared_arp_packets: list = None, shared_gw_mac_history: list = None) -> CheckResult:
    """
    ARP 欺骗检测

    4 个判断维度（详见 docs/checks/arp_spoof.md）：
      A: 同一 IP 的 MAC 变化次数（主信号）
      B: 单 MAC 发 Gratuitous ARP 频率
      C: 网关 MAC 时间漂移（与 rogue_router 共享）
      D: 攻击工具 OUI（v1 预留，不实现）

    采样时长 60 秒

    参数:
      shared_arp_packets: 与 loop/rogue_router 共享的 ARP 抓包（避免重复抓）
      shared_gw_mac_history: 与 rogue_router 共享的网关 MAC 历史
    """
    DURATION = 60  # 秒

    # ── Phase 1: 数据采集 ────────────────────────────────
    if shared_arp_packets is not None:
        arp_packets = shared_arp_packets
    else:
        arp_packets = _sniff_arp_packets(ctx.iface, duration=DURATION)

    if shared_gw_mac_history is not None:
        gateway_mac_history = shared_gw_mac_history
    else:
        gateway_mac_history = _monitor_gateway_mac(ctx.iface, ctx.gateway_ip, duration=DURATION)

    # ── Phase 2: 解析 ARP 包 ─────────────────────────────
    # 建立 ip → [mac, mac, ...] 映射
    ip_mac_map = _build_ip_mac_history(arp_packets)
    # 建立 mac → gratuitous_arp_count
    mac_garp_count = _count_garp_per_mac(arp_packets)

    # ── Phase 3: 4 个子判断 ──────────────────────────────
    sub_findings = [
        _check_ip_mac_churn(ip_mac_map),
        _check_garp_flood(mac_garp_count),
        _check_gateway_mac_drift(gateway_mac_history),
        # _check_attack_tool_oui(subnet_alive),  # v1 预留
    ]

    # ── Phase 4: 综合判定 ────────────────────────────────
    verdict, confidence, summary = _synthesize_verdict(sub_findings)

    # ── Phase 5: 证据 + 话术 ─────────────────────────────
    evidence = _build_evidence(ip_mac_map, mac_garp_count, sub_findings)
    remediation, questions = _build_onsite_playbook(verdict, ip_mac_map)

    return CheckResult(
        name="arp_spoof",
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

def _sniff_arp_packets(iface: str, duration: int) -> list:
    """抓 ARP 包（与 loop/rogue_router 共享）"""
    # TODO: scapy.sniff(iface=iface, filter="arp", timeout=duration)
    return []


def _monitor_gateway_mac(iface: str, gateway_ip: str, duration: int) -> list:
    """60 秒内网关 MAC 时间序列（与 rogue_router 共享）"""
    # TODO: 复用 rogue_router._monitor_gateway_mac()
    return []


# ============================================================
# Phase 2 — 解析
# ============================================================

def _build_ip_mac_history(arp_packets: list) -> dict[str, list[str]]:
    """
    解析所有 ARP 包，构建 {ip: [mac_出现顺序]}
    
    例: {"192.168.1.100": ["m1", "m2", "m1"], ...}

    TODO: 解析 scapy.ARP 包，提取 psrc (sender IP) 和 hwsrc (sender MAC)
    """
    return {}


def _count_garp_per_mac(arp_packets: list) -> dict[str, int]:
    """
    数每个 MAC 发 Gratuitous ARP 的次数
    Gratuitous ARP: ARP 请求中 sender IP == target IP
    
    返回: {mac: count}

    TODO: 解析 scapy.ARP，判断 op=1 (who-has) 且 psrc == pdst
    """
    return {}


# ============================================================
# Phase 3 — 4 个子判断
# ============================================================

def _check_ip_mac_churn(ip_mac_map: dict[str, list[str]]) -> SubFinding:
    """维度 A: 同一 IP 的 MAC 变化次数"""
    suspicious = {}  # {ip: 变化次数}
    for ip, macs in ip_mac_map.items():
        distinct = set(macs)
        # 出现 ≥ 2 个不同 MAC 算变化
        churn_count = len(distinct) - 1  # 减 1 因为首次出现不算变化
        if churn_count >= 1:
            suspicious[ip] = {
                "transition_count": churn_count,
                "macs": sorted(distinct),
            }

    if not suspicious:
        return SubFinding(
            dimension="ip_mac_churn",
            verdict=Verdict.NORMAL,
            raw_value={},
            note="60 秒内无 IP 出现 MAC 变化",
        )

    max_churn = max(v["transition_count"] for v in suspicious.values())
    if max_churn >= 2:
        v = Verdict.CRITICAL
    else:
        v = Verdict.WARNING

    return SubFinding(
        dimension="ip_mac_churn",
        verdict=v,
        raw_value=suspicious,
        note=f"{len(suspicious)} 个 IP 出现 MAC 变化，最大变化 {max_churn} 次",
    )


def _check_garp_flood(mac_garp_count: dict[str, int]) -> SubFinding:
    """维度 B: 单 MAC 发 Gratuitous ARP 频率"""
    if not mac_garp_count:
        return SubFinding(
            dimension="garp_flood",
            verdict=Verdict.NORMAL,
            raw_value={},
            note="60 秒内未抓到 Gratuitous ARP",
        )

    peak_mac, peak_count = max(mac_garp_count.items(), key=lambda kv: kv[1])
    if peak_count >= 20:
        v = Verdict.CRITICAL
    elif peak_count >= 10:
        v = Verdict.WARNING
    else:
        v = Verdict.NORMAL

    return SubFinding(
        dimension="garp_flood",
        verdict=v,
        raw_value={mac_garp_count},
        note=f"峰值 MAC {peak_mac} 发了 {peak_count} 个 Gratuitous ARP",
    )


def _check_gateway_mac_drift(gateway_mac_history: list[str]) -> SubFinding:
    """维度 C: 网关 MAC 时间漂移（与 rogue_router 共享）"""
    distinct_macs = set(gateway_mac_history)
    n = len(distinct_macs)
    if n >= 2:
        v = Verdict.WARNING
    else:
        v = Verdict.NORMAL
    return SubFinding(
        dimension="gateway_mac_drift",
        verdict=v,
        raw_value=sorted(distinct_macs),
        note=f"60 秒内网关 MAC 变化 {n} 次" + ("（漂移）" if n >= 2 else ""),
    )


# ============================================================
# Phase 4 — 综合判定
# ============================================================

def _synthesize_verdict(sub_findings: list[SubFinding]) -> tuple[Verdict, Confidence, str]:
    """按 docs/checks/arp_spoof.md §三 的决策树综合判定"""
    by_dim = {f.dimension: f for f in sub_findings}
    a = by_dim["ip_mac_churn"].verdict
    b = by_dim["garp_flood"].verdict
    c = by_dim["gateway_mac_drift"].verdict

    # MAC 来回变 + 高频广播双确认：CRITICAL
    if a == Verdict.CRITICAL and b == Verdict.CRITICAL:
        return (
            Verdict.CRITICAL,
            Confidence.HIGH,
            "强证据双信号确认 ARP 欺骗",
        )

    # 单信号：WARNING（中置信度）
    if a in (Verdict.WARNING, Verdict.CRITICAL) or b in (Verdict.WARNING, Verdict.CRITICAL):
        return (
            Verdict.WARNING,
            Confidence.MEDIUM,
            "检测到单信号异常（MAC 变化或 Gratuitous ARP 异常）",
        )

    # 弱信号：WARNING（低置信度）
    if c == Verdict.WARNING:
        return (
            Verdict.WARNING,
            Confidence.LOW,
            "网关 MAC 漂移，需结合 rogue_router 综合判断",
        )

    return (
        Verdict.NORMAL,
        Confidence.HIGH,
        "60 秒内未检测到 ARP 欺骗迹象",
    )


# ============================================================
# Phase 5 — 证据 + 话术
# ============================================================

def _build_evidence(
    ip_mac_map: dict,
    mac_garp_count: dict,
    sub_findings: list[SubFinding],
) -> list[EvidenceItem]:
    evidence = []
    by_dim = {f.dimension: f for f in sub_findings}

    # MAC 来回变的 IP
    churn = by_dim["ip_mac_churn"].raw_value
    if churn:
        evidence.append(EvidenceItem(
            type="ip_mac_churn",
            title=f"{len(churn)} 个 IP 出现 MAC 来回变化",
            items=[
                {
                    "ip": ip,
                    "macs": v["macs"],
                    "transition_count": v["transition_count"],
                }
                for ip, v in churn.items()
            ],
        ))

    # Gratuitous ARP 峰值 MAC
    if by_dim["garp_flood"].verdict != Verdict.NORMAL:
        top_macs = sorted(mac_garp_count.items(), key=lambda kv: kv[1], reverse=True)[:5]
        evidence.append(EvidenceItem(
            type="garp_flood",
            title="Gratuitous ARP 广播 Top 5 MAC",
            items=[{"mac": m, "count_per_min": c} for m, c in top_macs],
        ))

    return evidence


def _build_onsite_playbook(verdict: Verdict, ip_mac_map: dict) -> tuple[list[str], list[str]]:
    if verdict == Verdict.CRITICAL:
        return (
            [
                "立即在核心交换机查可疑 MAC 对应端口 → 拔线",
                "中毒主机断网杀毒（建议 Malwarebytes / 卡巴斯基全盘扫描）",
                "推荐方案：装 lanwatch_agent 持续监控 ARP 表，自动告警",
            ],
            [
                "客户问'网络被黑了吗'：是'有强证据显示有设备在发异常 ARP，可能是中毒主机'",
            ],
        )
    if verdict == Verdict.WARNING:
        return (
            [
                "现场观察可疑 IP / MAC 行为（持续掉线？网页跳转到陌生页？）",
                "在交换机上查可疑 MAC 端口 → 排查",
                "推荐方案：装 lanwatch_agent 持续监控",
            ],
            [
                "问客户：'最近是不是有电脑感觉变慢 / 弹广告 / 跳转到奇怪页面？'",
                "问客户：'最近有没有新员工入职带了笔记本？'",
            ],
        )
    return (
        [
            "60 秒内未检测到 ARP 欺骗迹象",
            "建议定期用 lanwatch_agent 自动巡检 ARP 表",
        ],
        [],
    )


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    test_cases = [
        # 1. 双信号 CRITICAL
        [
            SubFinding("ip_mac_churn", Verdict.CRITICAL, {"192.168.1.100": {"transition_count": 3, "macs": ["m1", "m2"]}}, ""),
            SubFinding("garp_flood", Verdict.CRITICAL, {"m1": 45}, ""),
            SubFinding("gateway_mac_drift", Verdict.WARNING, ["m1", "m2"], ""),
        ],
        # 2. 单信号 WARNING（仅 MAC churn）
        [
            SubFinding("ip_mac_churn", Verdict.WARNING, {"192.168.1.100": {"transition_count": 1, "macs": ["m1", "m2"]}}, ""),
            SubFinding("garp_flood", Verdict.NORMAL, {}, ""),
            SubFinding("gateway_mac_drift", Verdict.NORMAL, ["m1"], ""),
        ],
        # 3. 全 NORMAL
        [
            SubFinding("ip_mac_churn", Verdict.NORMAL, {}, ""),
            SubFinding("garp_flood", Verdict.NORMAL, {}, ""),
            SubFinding("gateway_mac_drift", Verdict.NORMAL, ["m1"], ""),
        ],
        # 4. 弱信号 WARNING（仅网关漂移）
        [
            SubFinding("ip_mac_churn", Verdict.NORMAL, {}, ""),
            SubFinding("garp_flood", Verdict.NORMAL, {}, ""),
            SubFinding("gateway_mac_drift", Verdict.WARNING, ["m1", "m2", "m1"], ""),
        ],
    ]

    expected = ["critical/high", "warning/medium", "normal/high", "warning/low"]
    for i, (findings, exp) in enumerate(zip(test_cases, expected)):
        v, c, s = _synthesize_verdict(findings)
        print(f"[Test {i+1}] {v.value}/{c.value} — 预期 {exp} | 摘要: {s}")