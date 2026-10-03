"""
loop_pseudo.py — 网络环路检测伪代码

⚠️ 这是 SOP 细化用的伪代码，不是 v1.0 最终实现
- 函数签名已按 v1.0 提前定，方便后续直接实现
- 复用 rogue_router_pseudo.py 的通用类型（Verdict/Confidence/CheckResult/SubFinding/EvidenceItem/DiagContext）
- TODO 标了实现细节，阈值按 docs/checks/loop.md

最终实现路径（v1.0）：
    lanwatch_diagnostic/checks/loop.py

参考决策树：docs/checks/loop.md
"""

# v1.0 实现时改为：
# from lanwatch_diagnostic.common import (
#     Verdict, Confidence, SubFinding, EvidenceItem, CheckResult, DiagContext,
# )
# 这里为了清晰保留 enum 重复定义的位置标注

import sys
sys.path.insert(0, ".")
from rogue_router_pseudo import (  # 复用通用类型
    Verdict, Confidence, SubFinding, EvidenceItem, CheckResult, DiagContext,
)


# ============================================================
# 主入口
# ============================================================

def check_loop(ctx: DiagContext) -> CheckResult:
    """
    网络环路检测

    4 个判断维度（详见 docs/checks/loop.md）：
      A: 广播包速率峰值（主信号）
      B: STP TCN 包数量（环路最强证据）
      C: 速率持续时间（区分瞬时高峰 vs 持续环路）
      D: ARP 风暴（辅助信号）

    采样时长 30 秒（可由 v1.0 通过 ctx.options.loop_duration 覆盖）
    """
    DURATION = 30  # 秒

    # ── Phase 1: 30 秒采样 ────────────────────────────────
    broadcast_packets = _sniff_broadcast_packets(ctx.iface, duration=DURATION)
    stp_bpdus         = _sniff_stp_bpdus(ctx.iface, duration=DURATION)
    arp_packets       = _sniff_arp_packets(ctx.iface, duration=DURATION)

    # 计算速率（每秒包数列表）
    broadcast_rate_per_sec = _calc_rate_per_second(broadcast_packets, duration=DURATION)
    arp_rate_per_sec       = _calc_rate_per_second(arp_packets, duration=DURATION)

    # 统计 STP TCN 包数
    tcn_count = _count_tcn_bpdus(stp_bpdus)

    # ── Phase 2: 4 个子判断 ──────────────────────────────
    sub_findings = [
        _check_broadcast_rate(broadcast_rate_per_sec),
        _check_stp_tcn(tcn_count),
        _check_rate_curve(broadcast_rate_per_sec),
        _check_arp_storm(arp_rate_per_sec),
    ]

    # ── Phase 3: 综合判定 ────────────────────────────────
    verdict, confidence, summary = _synthesize_verdict(sub_findings)

    # ── Phase 4: 证据 + 现场话术 ─────────────────────────
    evidence = _build_evidence(broadcast_rate_per_sec, stp_bpdus, sub_findings)
    remediation, questions = _build_onsite_playbook(verdict)

    return CheckResult(
        name="loop",
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

def _sniff_broadcast_packets(iface: str, duration: int) -> list:
    """
    抓所有广播包（ether dst = ff:ff:ff:ff:ff:ff）

    TODO: scapy.sniff(iface=iface, filter="ether dst ff:ff:ff:ff:ff:ff", timeout=duration)
    """
    # TODO: 真实实现
    return []  # placeholder


def _sniff_stp_bpdus(iface: str, duration: int) -> list:
    """
    抓 STP BPDU 包（ether dst = 01:80:c2:00:00:00）

    返回的每个元素是 scapy BPDU 对象，可读 .type / .flags / .root_id 等

    TODO: scapy.sniff(iface=iface, filter="ether dst 01:80:c2:00:00:00", timeout=duration)
    """
    # TODO: 真实实现
    return []  # placeholder


def _sniff_arp_packets(iface: str, duration: int) -> list:
    """
    抓所有 ARP 包（与 arp_spoof_pseudo.py 共享接口）
    """
    # TODO: scapy.sniff(iface=iface, filter="arp", timeout=duration)
    return []


def _calc_rate_per_second(packets: list, duration: int) -> list[int]:
    """
    把包按时间分桶，返回每秒包数列表（长度 = duration）

    TODO: 用 scapy Packet.time 拿到 timestamp，按 int(time - start_time) 分桶
    """
    # TODO: 真实实现
    return [0] * duration


def _count_tcn_bpdus(bpdus: list) -> int:
    """
    数 STP TCN（Topology Change Notification）包

    TCN 特征：BPDU type = 0x80 (TCN)，普通 Config BPDU type = 0x00
    TODO: 解析 scapy STP BPDU flags & type
    """
    # TODO: 真实实现
    return 0


# ============================================================
# Phase 2 — 4 个子判断
# ============================================================

def _check_broadcast_rate(rate_per_sec: list[int]) -> SubFinding:
    """维度 A: 广播速率峰值"""
    peak = max(rate_per_sec) if rate_per_sec else 0
    if peak >= 500:
        v = Verdict.CRITICAL
    elif peak >= 50:
        v = Verdict.WARNING
    else:
        v = Verdict.NORMAL
    return SubFinding(
        dimension="broadcast_rate",
        verdict=v,
        raw_value=peak,
        note=f"广播速率峰值 {peak} pps" + ("（确认环路）" if peak >= 500 else ("（异常）" if peak >= 50 else "")),
    )


def _check_stp_tcn(count: int) -> SubFinding:
    """维度 B: STP TCN 包数"""
    if count >= 3:
        v = Verdict.CRITICAL
    elif count >= 1:
        v = Verdict.WARNING
    else:
        v = Verdict.NORMAL
    return SubFinding(
        dimension="stp_tcn",
        verdict=v,
        raw_value=count,
        note=f"30 秒内抓到 {count} 个 STP TCN BPDU" + ("（环路在摇摆）" if count >= 3 else ""),
    )


def _check_rate_curve(rate_per_sec: list[int]) -> SubFinding:
    """维度 C: 速率持续时间（区分瞬时 vs 持续）"""
    high_seconds = sum(1 for r in rate_per_sec if r >= 200)
    if high_seconds >= 5:
        v = Verdict.WARNING
    else:
        v = Verdict.NORMAL
    return SubFinding(
        dimension="rate_curve",
        verdict=v,
        raw_value=high_seconds,
        note=f"持续 ≥ 200 pps 共 {high_seconds} 秒" + ("（持续高，非瞬时）" if high_seconds >= 5 else ""),
    )


def _check_arp_storm(arp_rate_per_sec: list[int]) -> SubFinding:
    """维度 D: ARP 风暴"""
    peak = max(arp_rate_per_sec) if arp_rate_per_sec else 0
    if peak >= 30:
        v = Verdict.WARNING
    else:
        v = Verdict.NORMAL
    return SubFinding(
        dimension="arp_storm",
        verdict=v,
        raw_value=peak,
        note=f"ARP 速率峰值 {peak} pps" + ("（伴随广播风暴）" if peak >= 30 else ""),
    )


# ============================================================
# Phase 3 — 综合判定
# ============================================================

def _synthesize_verdict(sub_findings: list[SubFinding]) -> tuple[Verdict, Confidence, str]:
    """按 docs/checks/loop.md §三 的决策树综合判定"""
    by_dim = {f.dimension: f for f in sub_findings}
    a = by_dim["broadcast_rate"].verdict
    b = by_dim["stp_tcn"].verdict
    c = by_dim["rate_curve"].verdict
    d = by_dim["arp_storm"].verdict

    # 速率 + STP 双确认：CRITICAL
    if a == Verdict.CRITICAL and b in (Verdict.WARNING, Verdict.CRITICAL):
        return (
            Verdict.CRITICAL,
            Confidence.HIGH,
            "强证据双信号确认网络环路",
        )

    # 单信号：WARNING（中置信度）
    if a in (Verdict.WARNING, Verdict.CRITICAL) or b in (Verdict.WARNING, Verdict.CRITICAL):
        return (
            Verdict.WARNING,
            Confidence.MEDIUM,
            "检测到单信号异常（广播速率或 STP 变化），建议现场排查",
        )

    # 弱信号：WARNING（低置信度）
    if c == Verdict.WARNING or d == Verdict.WARNING:
        return (
            Verdict.WARNING,
            Confidence.LOW,
            "检测到弱信号异常（持续高广播或 ARP 风暴），需现场确认",
        )

    return (
        Verdict.NORMAL,
        Confidence.HIGH,
        "30 秒内未检测到网络环路迹象",
    )


# ============================================================
# Phase 4 — 证据 + 话术
# ============================================================

def _build_evidence(
    rate_per_sec: list[int],
    bpdus: list,
    sub_findings: list[SubFinding],
) -> list[EvidenceItem]:
    evidence = []

    by_dim = {f.dimension: f for f in sub_findings}

    # 广播速率折线图数据
    if max(rate_per_sec) > 50:
        evidence.append(EvidenceItem(
            type="broadcast_rate_chart",
            title="30 秒广播包速率时间曲线",
            items=[{"time_sec": i, "pps": p} for i, p in enumerate(rate_per_sec)],
        ))

    # STP TCN 样本
    if by_dim["stp_tcn"].verdict != Verdict.NORMAL:
        evidence.append(EvidenceItem(
            type="stp_tcn_sample",
            title=f"抓到 {len(bpdus)} 个 STP BPDU（含 TCN）",
            items=[],  # TODO: 真实实现时填 BPDU 详细信息
        ))

    return evidence


def _build_onsite_playbook(verdict: Verdict) -> tuple[list[str], list[str]]:
    if verdict == Verdict.CRITICAL:
        return (
            [
                "立即在核心交换机上执行: show spanning-tree blocked ports",
                "拔除最近新接的网线（最常见环路源）",
                "推荐方案：装 lanwatch_agent 持续监控广播速率，自动告警",
            ],
            [
                "客户问'网络有问题吗'：是'有强证据显示存在网络环路，需要立即排查'",
            ],
        )
    if verdict == Verdict.WARNING:
        return (
            [
                "现场询问客户最近是否新接网线 / 新加设备",
                "登录交换机检查 STP 状态、端口流量",
                "推荐方案：装 lanwatch_agent 持续监控",
            ],
            [
                "问客户：'最近一两天有没有动过网线或加设备？'",
                "问客户：'网络卡顿大概什么时候开始的？'",
            ],
        )
    return (
        [
            "30 秒内未检测到网络环路迹象",
            "建议定期用 lanwatch_agent 自动巡检广播速率",
        ],
        [],
    )


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    test_cases = [
        # 1. 双信号 CRITICAL（速率高 + STP TCN）
        [
            SubFinding("broadcast_rate", Verdict.CRITICAL, 850, ""),
            SubFinding("stp_tcn", Verdict.CRITICAL, 5, ""),
            SubFinding("rate_curve", Verdict.WARNING, 22, ""),
            SubFinding("arp_storm", Verdict.WARNING, 120, ""),
        ],
        # 2. 单信号 WARNING（仅速率高）
        [
            SubFinding("broadcast_rate", Verdict.WARNING, 280, ""),
            SubFinding("stp_tcn", Verdict.NORMAL, 0, ""),
            SubFinding("rate_curve", Verdict.WARNING, 15, ""),
            SubFinding("arp_storm", Verdict.NORMAL, 20, ""),
        ],
        # 3. 全 NORMAL
        [
            SubFinding("broadcast_rate", Verdict.NORMAL, 15, ""),
            SubFinding("stp_tcn", Verdict.NORMAL, 0, ""),
            SubFinding("rate_curve", Verdict.NORMAL, 0, ""),
            SubFinding("arp_storm", Verdict.NORMAL, 5, ""),
        ],
        # 4. 弱信号 WARNING（瞬时 ARP 风暴）
        [
            SubFinding("broadcast_rate", Verdict.NORMAL, 30, ""),
            SubFinding("stp_tcn", Verdict.NORMAL, 0, ""),
            SubFinding("rate_curve", Verdict.NORMAL, 2, ""),
            SubFinding("arp_storm", Verdict.WARNING, 80, ""),
        ],
    ]

    expected = ["critical/high", "warning/medium", "normal/high", "warning/low"]
    for i, (findings, exp) in enumerate(zip(test_cases, expected)):
        v, c, s = _synthesize_verdict(findings)
        print(f"[Test {i+1}] {v.value}/{c.value} — 预期 {exp} | 摘要: {s}")

    # 预期：
    # [Test 1] critical/high — 预期 critical/high | 摘要: 强证据双信号确认网络环路
    # [Test 2] warning/medium — 预期 warning/medium | 摘要: 检测到单信号异常...
    # [Test 3] normal/high — 预期 normal/high | 摘要: 30 秒内未检测到网络环路迹象
    # [Test 4] warning/low — 预期 warning/low | 摘要: 检测到弱信号异常...