#!/usr/bin/env python3
"""
passive_diag.py — Lanwatch Diagnostic 被动观察版 MVP v0.1

⚠️ 仅做被动观察——不主动扫描、不发包、不嗅探
  - 读本机 ARP 表（已存在，不算主动）
  - 读本机路由表 / DNS 配置
  - traceroute 到公网（单向探测，不动客户设备）
  - 多次采样 ARP 表（5 秒间隔）看 MAC 漂移

🔒 隐私保护
  - 报告本地保存（不进 git）
  - 文件名带 hash 不带客户名
  - 不上传 Server

🚀 快速跑：
  pip install click jinja2 psutil
  python3 passive_diag.py --label "正常客户A" --company "客户A有限公司"
"""

import os
import sys
import re
import json
import time
import hashlib
import ipaddress
import platform
import datetime
import subprocess
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import click
import jinja2
import psutil


# ============================================================
# 类型定义
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
    dimension: str
    verdict: Verdict
    raw_value: any
    note: str = ""


@dataclass
class EvidenceItem:
    type: str
    title: str
    items: list = field(default_factory=list)


@dataclass
class CheckResult:
    name: str
    verdict: Verdict
    confidence: Confidence
    summary: str
    sub_findings: list
    evidence: list
    remediation: list
    onsite_questions: list = field(default_factory=list)


# ============================================================
# 数据采集层（只读本机系统状态）
# ============================================================

def get_arp_table() -> dict:
    """读本机 ARP 表"""
    system = platform.system().lower()
    arp = {}
    try:
        if system in ("darwin", "linux"):
            out = subprocess.check_output(["arp", "-an"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                # macOS: ? (192.168.1.1) at 00:11:22:33:44:55 on en0 ...
                m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-fA-F:]{17})", line)
                if m:
                    arp[m.group(1)] = m.group(2).lower()
        elif system == "windows":
            out = subprocess.check_output(["arp", "-a"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})", line)
                if m:
                    arp[m.group(1)] = m.group(2).replace("-", ":").lower()
    except Exception as e:
        click.echo(f"  ⚠️  读 ARP 表失败: {e}", err=True)
    return arp


def get_default_gateway() -> Optional[str]:
    """读默认网关 IP"""
    system = platform.system().lower()
    try:
        if system == "darwin":
            out = subprocess.check_output(["netstat", "-rn"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if line.startswith("default"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return parts[1]
        elif system == "linux":
            out = subprocess.check_output(["ip", "route"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if line.startswith("default"):
                    parts = line.split()
                    if len(parts) >= 3:
                        return parts[2]
        elif system == "windows":
            out = subprocess.check_output(["route", "print", "0.0.0.0"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                m = re.search(r"0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)", line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None


def get_local_ip_and_mask():
    """获取本机主接口的 IP 和子网掩码（CIDR 格式）

    跨平台实现：优先 psutil（更稳定），fallback ifconfig/ipconfig
    跳过 lo0/loopback/虚拟接口，优先 VPN tunnel 接口（utun*/tun*/tap*/ppp*）

    返回: (ip, mask, iface) 三元组
    """
    # 策略 1：psutil 收集候选，优先 VPN tunnel
    candidates = []  # [(iface, ip, mask)]
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            # 跳过明显不需要的接口
            if iface.startswith(("lo", "docker", "veth", "br-", "awdl", "llw", "ham")):
                continue
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if ip.startswith("127."):
                        continue
                    mask = addr.netmask
                    if mask:
                        bits = ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
                        candidates.append((iface, ip, f"/{bits}"))
    except Exception:
        pass

    if candidates:
        # 优先 VPN tunnel 接口（utun*/tun*/tap*/ppp*）
        for iface, ip, mask in candidates:
            if iface.startswith(("utun", "tun", "tap", "ppp")):
                return ip, mask, iface
        # 否则取第一个物理接口（en0/en1/eth0 等）
        return candidates[0][1], candidates[0][2], candidates[0][0]

    # 策略 2：fallback 到系统命令（处理 psutil 异常情况）
    system = platform.system().lower()
    try:
        if system == "darwin":
            out = subprocess.check_output(["ifconfig"], text=True, stderr=subprocess.DEVNULL)
            current = ""
            for line in out.splitlines():
                if line and not line.startswith("\t") and line.endswith(":"):
                    current = line.rstrip(":")
                    continue
                if current.startswith("lo"):
                    continue
                m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)\s+netmask\s+(0x\S+)", line)
                if m:
                    hex_mask = m.group(2).replace("0x", "")
                    bits = int(hex_mask, 16).bit_length()
                    return m.group(1), f"/{bits}", current
        elif system == "linux":
            out = subprocess.check_output(["ip", "-o", "-f", "inet", "addr", "show"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if " lo " in line or "docker" in line:
                    continue
                m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)\s+\S+\s+(\S+)", line)
                if m:
                    return m.group(1), f"/{m.group(2)}", m.group(3)
        elif system == "windows":
            out = subprocess.check_output(["ipconfig"], text=True, stderr=subprocess.DEVNULL)
            m = re.search(r"IPv4 Address.*?:\s*(\d+\.\d+\.\d+\.\d+)", out)
            if m:
                return m.group(1), "/24", None
    except Exception:
        pass

    return None, None, None


def get_dns_servers() -> list:
    """读本机 DNS 服务器列表"""
    system = platform.system().lower()
    dns = []
    try:
        if system == "darwin":
            out = subprocess.check_output(["scutil", "--dns"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                m = re.search(r"nameserver\[\d+\]\s*:\s*(\S+)", line)
                if m and m.group(1) not in dns:
                    dns.append(m.group(1))
        elif system == "linux":
            try:
                with open("/etc/resolv.conf") as f:
                    for line in f:
                        m = re.match(r"\s*nameserver\s+(\S+)", line)
                        if m and m.group(1) not in dns:
                            dns.append(m.group(1))
            except FileNotFoundError:
                pass
        elif system == "windows":
            out = subprocess.check_output(["ipconfig", "/all"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                m = re.search(r"DNS Servers.*?:\s*(\d+\.\d+\.\d+\.\d+)", line)
                if m and m.group(1) not in dns:
                    dns.append(m.group(1))
    except Exception:
        pass
    return dns


def get_routing_table() -> list:
    """读本机路由表"""
    system = platform.system().lower()
    routes = []
    try:
        if system in ("darwin", "linux"):
            out = subprocess.check_output(["netstat", "-rn"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                parts = line.split()
                # macOS: "default  192.168.1.1  ..." / Linux: "0.0.0.0  192.168.1.1  0.0.0.0  ..."
                if line.startswith("default") or (len(parts) >= 1 and parts[0] == "0.0.0.0"):
                    routes.append(parts)
        elif system == "windows":
            out = subprocess.check_output(["route", "print"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4 and re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[0]):
                    routes.append(parts)
    except Exception:
        pass
    return routes


def get_iface_stats() -> dict:
    """读接口流量统计（含错误/丢包计数）"""
    try:
        return {iface: {
            "bytes_sent": c.bytes_sent,
            "bytes_recv": c.bytes_recv,
            "packets_sent": c.packets_sent,
            "packets_recv": c.packets_recv,
            "errin": c.errin,
            "errout": c.errout,
            "dropin": c.dropin,
            "dropout": c.dropout,
        } for iface, c in psutil.net_io_counters(pernic=True).items()}
    except Exception:
        return {}


def traceroute(target: str = "8.8.8.8", max_hops: int = 8, hard_timeout: int = 8) -> list:
    """traceroute 到目标（macOS 在 /usr/sbin/，无需 sudo）

    使用 Popen + 手动 kill 实现硬超时（subprocess.check_output 的 timeout 在 macOS 上不可靠）
    """
    system = platform.system().lower()

    # macOS traceroute 在 /usr/sbin/，可能不在 PATH
    tr_paths = [
        "/usr/sbin/traceroute",
        "/usr/bin/traceroute",
        "/sbin/traceroute",
        "traceroute",
    ]

    cmd = None
    for p in tr_paths:
        if os.path.exists(p) or p == "traceroute":
            if system in ("darwin", "linux"):
                cmd = [p, "-m", str(max_hops), "-q", "1", "-w", "1", target]
            else:  # Windows
                cmd = [p, "-h", str(max_hops), "-w", "1000", target]
            break

    if cmd is None:
        return [{"hop": 0, "ip": "tool_missing", "note": "traceroute 命令未找到"}]

    try:
        # 用 Popen + communicate(timeout) 实现硬超时
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            out, err = proc.communicate(timeout=hard_timeout)
        except subprocess.TimeoutExpired:
            # 硬杀进程（避免僵尸进程）
            proc.kill()
            try:
                proc.communicate(timeout=2)
            except Exception:
                pass
            return [{"hop": 0, "ip": "timeout", "note": f"traceroute 超时（{hard_timeout}s）"}]

        # 进程退出但可能没输出（macOS 无 sudo 时常见）
        if not out:
            err_msg = err.strip()[:80] if err else "无输出"
            return [{"hop": 0, "ip": "no_output", "note": f"traceroute 无输出（{err_msg}）"}]

    except FileNotFoundError:
        return [{"hop": 0, "ip": "tool_missing", "note": "traceroute 命令未找到"}]
    except Exception as e:
        return [{"hop": 0, "ip": "error", "note": f"traceroute 失败: {e}"}]

    hops = []
    for line in out.splitlines():
        m = re.match(r"^\s*(\d+)\s+(\S+)", line)
        if m:
            hop_num = int(m.group(1))
            ip_or_host = m.group(2).strip("()")
            # * 表示超时，跳过
            if ip_or_host == "*":
                continue
            hops.append({"hop": hop_num, "ip": ip_or_host})
    return hops


# ============================================================
# 4 个 check（被动版本）
# ============================================================

# 内网段白名单（RFC1918 + CGNAT）
PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
]

ABNORMAL_NETS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
]


def _is_private(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in n for n in PRIVATE_NETS)
    except ValueError:
        return False


def _is_abnormal(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in n for n in ABNORMAL_NETS)
    except ValueError:
        return False


def _strip_zone_id(ip_str: str) -> str:
    """去除 IPv6 zone id (如 fe80::5%en0 → fe80::5)"""
    if "%" in ip_str:
        return ip_str.split("%")[0]
    return ip_str


def _is_link_local(ip_str: str) -> bool:
    """判断 IPv6 link-local (fe80::/10)，含 zone id"""
    try:
        addr = ipaddress.ip_address(_strip_zone_id(ip_str))
        if isinstance(addr, ipaddress.IPv6Address):
            return addr.is_link_local
        return False
    except ValueError:
        return False


# Check 1: 私接小路由（被动版）
def check_rogue_router(ctx: dict) -> CheckResult:
    """
    被动版：仅检查本机 ARP 表
    - 网关 MAC 是否存在
    - ARP 表条目数（异常多=扫描痕迹）
    - 主动扫描维度缺失（需客户授权）
    """
    arp = ctx["arp_table"]
    gateway = ctx["gateway"]

    findings = []

    # 网关 MAC 是否在 ARP 表
    gw_mac = arp.get(gateway)
    findings.append(SubFinding(
        dimension="gateway_mac_present",
        verdict=Verdict.NORMAL if gw_mac else Verdict.WARNING,
        raw_value=gw_mac,
        note=f"网关 {gateway} MAC: {gw_mac}" if gw_mac else f"网关 {gateway} 不在 ARP 表中",
    ))

    # ARP 表规模
    findings.append(SubFinding(
        dimension="arp_table_size",
        verdict=Verdict.NORMAL if len(arp) < 100 else Verdict.WARNING,
        raw_value=len(arp),
        note=f"本机 ARP 表共 {len(arp)} 条记录" + ("（偏多）" if len(arp) >= 100 else ""),
    ))

    return CheckResult(
        name="rogue_router",
        verdict=Verdict.NORMAL,
        confidence=Confidence.LOW,
        summary="被动观察：仅读取本机 ARP 表，主动扫描维度缺失（需客户授权）",
        sub_findings=findings,
        evidence=[],
        remediation=[
            "⚠️ 被动版无法判定私接路由",
            "建议授权后跑主动扫描：ARP 子网扫描 + DHCP probe",
        ],
        onsite_questions=[],
    )


# Check 2: 网络环路（被动版）
def check_loop(ctx: dict) -> CheckResult:
    """
    被动版：基于本机接口流量统计
    - 高丢包率 / 错误率 可能 = 环路
    - 注意：单凭接口统计不能确诊，需主动 sniff 验证
    """
    stats = ctx["iface_stats"]

    findings = []
    worst_verdict = Verdict.NORMAL

    for iface, s in stats.items():
        if iface.startswith(("lo", "docker", "veth", "br-", "awdl", "llw", "utun")):
            continue  # 跳过 loopback / 虚拟接口

        total_packets = max(s["packets_sent"] + s["packets_recv"], 1)
        err_rate = (s["errin"] + s["errout"]) / total_packets
        drop_rate = (s["dropin"] + s["dropout"]) / total_packets

        if err_rate > 0.05 or drop_rate > 0.05:
            v = Verdict.WARNING
            worst_verdict = Verdict.WARNING
            note = f"{iface}: 丢包率 {drop_rate:.2%}, 错包率 {err_rate:.2%}（异常）"
        else:
            v = Verdict.NORMAL
            note = f"{iface}: 丢包率 {drop_rate:.2%}, 错包率 {err_rate:.2%}"

        findings.append(SubFinding(
            dimension=f"iface_{iface}",
            verdict=v,
            raw_value={"err_rate": round(err_rate, 4), "drop_rate": round(drop_rate, 4)},
            note=note,
        ))

    return CheckResult(
        name="loop",
        verdict=worst_verdict,
        confidence=Confidence.LOW,
        summary="被动观察：基于接口统计（无主动 sniff 广播包，置信度低）",
        sub_findings=findings,
        evidence=[],
        remediation=[
            "如怀疑环路，需授权后跑主动 sniff 30 秒广播包速率",
        ],
        onsite_questions=[],
    )


# Check 3: ARP 欺骗（被动版）
def check_arp_spoof(ctx: dict) -> CheckResult:
    """
    被动版：间隔 5 秒两次采样 ARP 表
    - MAC 变化的 IP = 可疑（可能是 ARP 欺骗或正常续租）
    """
    arp1 = ctx["arp_table"]
    arp2 = ctx["arp_table_5s_later"]

    findings = []

    # 找 MAC 变化的 IP
    changed = {}
    for ip in arp1:
        if ip in arp2 and arp1[ip] != arp2[ip]:
            changed[ip] = {"from": arp1[ip], "to": arp2[ip]}

    # 找新增 / 消失的 IP
    new_ips = set(arp2.keys()) - set(arp1.keys())
    gone_ips = set(arp1.keys()) - set(arp2.keys())

    if changed:
        v = Verdict.WARNING
        note = f"{len(changed)} 个 IP 的 MAC 在 5 秒内变化"
    elif new_ips or gone_ips:
        v = Verdict.NORMAL
        note = f"ARP 表稳定（新增 {len(new_ips)} / 消失 {len(gone_ips)} 条）"
    else:
        v = Verdict.NORMAL
        note = "ARP 表 5 秒内完全无变化（稳定）"

    findings.append(SubFinding(
        dimension="arp_mac_churn",
        verdict=v,
        raw_value=changed,
        note=note,
    ))

    evidence = []
    if changed:
        evidence.append(EvidenceItem(
            type="arp_mac_change",
            title=f"{len(changed)} 个 IP 的 MAC 在 5 秒内变化",
            items=[{"ip": ip, "from": d["from"], "to": d["to"]} for ip, d in changed.items()],
        ))

    return CheckResult(
        name="arp_spoof",
        verdict=v,
        confidence=Confidence.MEDIUM,
        summary=note,
        sub_findings=findings,
        evidence=evidence,
        remediation=[
            "如发现 MAC 变化，建议授权后跑主动 sniff 60 秒 ARP 包做精准判定",
            "可能是正常的 DHCP 续租——结合现场情况判断",
        ],
        onsite_questions=[],
    )


# Check 4: 组网结构（被动版，全维度）
def check_topology(ctx: dict) -> CheckResult:
    """
    被动版：路由表 + DNS + traceroute（最完整的被动 check）
    - 网关是否在同子网（强信号）
    - DNS 位置
    - 路由表异常
    - traceroute 跳数
    """
    findings = []
    local_ip = ctx["local_ip"]
    netmask = ctx["netmask"]
    gateway = ctx["gateway"]
    local_iface = ctx.get("local_iface", "")
    is_vpn_tunnel = local_iface and local_iface.startswith(("utun", "tun", "tap", "ppp"))

    # 维度 B：网关是否在同子网（强信号）
    b_verdict = Verdict.NORMAL
    b_note = ""
    b_raw = {}
    try:
        subnet = ipaddress.ip_network(f"{local_ip}{netmask}", strict=False)
        gw_in_subnet = ipaddress.ip_address(gateway) in subnet

        # VPN tunnel 场景跳过严格 subnet 检查（split-tunnel 默认网关在物理 en0）
        if is_vpn_tunnel and not gw_in_subnet:
            b_verdict = Verdict.NORMAL
            b_raw = {"subnet": str(subnet), "gateway": gateway, "in_subnet": False, "is_vpn_tunnel": True}
            b_note = f"VPN tunnel 场景（{local_iface}）：默认网关 {gateway} 在物理网卡 split-tunnel 正常"
        else:
            b_verdict = Verdict.NORMAL if gw_in_subnet else Verdict.CRITICAL
            b_raw = {"subnet": str(subnet), "gateway": gateway, "in_subnet": gw_in_subnet}
            b_note = f"网关 {gateway} {'在' if gw_in_subnet else '不在'} {subnet} 内" + ("（拓扑错配）" if not gw_in_subnet else "")
    except Exception as e:
        b_note = f"无法判定: {e}"

    findings.append(SubFinding(
        dimension="gateway_subnet",
        verdict=b_verdict,
        raw_value=b_raw,
        note=b_note,
    ))

    # 维度 C：DNS 服务器位置
    dns_servers = ctx["dns_servers"]
    dns_locations = []
    c_verdict = Verdict.NORMAL

    if not dns_servers:
        c_verdict = Verdict.WARNING
        c_note = "本机未配置 DNS 服务器"
    else:
        for dns in dns_servers:
            # 跳过 IPv6 link-local（如 fe80::5%en0）
            if _is_link_local(dns):
                continue
            if _is_abnormal(dns):
                location = "abnormal"
                c_verdict = Verdict.CRITICAL
            elif _is_private(dns):
                location = "private"
            else:
                location = "public"
                if c_verdict != Verdict.CRITICAL:
                    c_verdict = Verdict.WARNING
            dns_locations.append({"ip": dns, "location": location})
        c_note = f"DNS: {', '.join(d['ip'] + '(' + d['location'] + ')' for d in dns_locations)}" if dns_locations else "本机 DNS 均为 link-local（已忽略）"

    findings.append(SubFinding(
        dimension="dns_location",
        verdict=c_verdict,
        raw_value=dns_locations,
        note=c_note,
    ))

    # 维度 D：默认路由数（VPN tunnel 场景忽略多路由告警）
    routes = ctx["routing_table"]
    default_routes = [r for r in routes if r[0] in ("default", "0.0.0.0")]

    if is_vpn_tunnel:
        # split-tunnel 下多默认路由是预期，忽略
        if not default_routes:
            d_verdict = Verdict.CRITICAL
            d_note = "VPN tunnel 场景下无默认路由（异常）"
        else:
            d_verdict = Verdict.NORMAL
            d_note = f"VPN tunnel split-tunnel：{len(default_routes)} 条默认路由是预期"
    else:
        if not default_routes:
            d_verdict = Verdict.CRITICAL
            d_note = "无默认路由（无法上外网）"
        elif len(default_routes) >= 4:
            d_verdict = Verdict.WARNING
            d_note = f"{len(default_routes)} 条默认路由（偏多）"
        else:
            d_verdict = Verdict.NORMAL
            d_note = f"{len(default_routes)} 条默认路由（正常）"

    findings.append(SubFinding(
        dimension="default_route_count",
        verdict=d_verdict,
        raw_value=len(default_routes),
        note=d_note,
    ))

    # 维度 A：traceroute 跳数
    hops = ctx["traceroute_hops"]
    hop_count = len(hops) if hops else 0
    a_verdict = Verdict.WARNING if hop_count > 5 else Verdict.NORMAL
    a_note = f"到 8.8.8.8 共 {hop_count} 跳" + ("（多层企业网）" if 5 < hop_count <= 10 else ("（异常绕路）" if hop_count > 10 else ""))

    findings.append(SubFinding(
        dimension="traceroute_hops",
        verdict=a_verdict,
        raw_value=hop_count,
        note=a_note,
    ))

    # 综合判定
    if b_verdict == Verdict.CRITICAL or d_verdict == Verdict.CRITICAL:
        verdict = Verdict.CRITICAL
        confidence = Confidence.HIGH
        summary = "拓扑严重错配（网关或路由配置错误）"
    elif c_verdict in (Verdict.WARNING, Verdict.CRITICAL) or d_verdict == Verdict.WARNING:
        verdict = Verdict.WARNING
        confidence = Confidence.MEDIUM
        summary = "DNS 或路由表异常"
    elif a_verdict == Verdict.WARNING:
        verdict = Verdict.WARNING
        confidence = Confidence.LOW
        summary = "公网跳数较多"
    else:
        verdict = Verdict.NORMAL
        confidence = Confidence.MEDIUM
        summary = "拓扑结构正常"

    return CheckResult(
        name="topology",
        verdict=verdict,
        confidence=confidence,
        summary=summary,
        sub_findings=findings,
        evidence=[],
        remediation=[
            "如有问题，检查路由器配置 / 路由表 / DNS 设置",
        ],
        onsite_questions=[],
    )


# ============================================================
# Runner（并发跑 4 个 check）
# ============================================================

def run_all_checks(label: str, no_traceroute: bool = False) -> dict:
    """并发跑 4 个 check"""

    click.echo("📊 采集本机状态...")

    # 数据采集
    arp_table_1 = get_arp_table()
    gateway = get_default_gateway()
    local_ip, netmask, local_iface = get_local_ip_and_mask()
    dns_servers = get_dns_servers()
    routing_table = get_routing_table()
    iface_stats = get_iface_stats()

    click.echo(f"   本机 IP: {local_ip}{netmask}")
    click.echo(f"   默认网关: {gateway}")
    click.echo(f"   DNS: {dns_servers}")
    click.echo(f"   ARP 表条目: {len(arp_table_1)}")

    # ARP 表二次采样（5 秒后）
    click.echo("\n⏱️  等待 5 秒做 ARP 表二次采样（用于检测 MAC 漂移）...")
    time.sleep(5)
    arp_table_2 = get_arp_table()

    click.echo("\n🌐 traceroute 到 8.8.8.8（单向探测，不动客户设备）...")
    if no_traceroute:
        hops = []
        click.echo("   跳过（--no-traceroute）")
    else:
        hops = traceroute("8.8.8.8")
        click.echo(f"   共 {len(hops)} 跳")

    # 准备 ctx
    ctx = {
        "label": label,
        "arp_table": arp_table_1,
        "arp_table_5s_later": arp_table_2,
        "gateway": gateway,
        "local_ip": local_ip,
        "netmask": netmask,
        "local_iface": local_iface,
        "dns_servers": dns_servers,
        "routing_table": routing_table,
        "iface_stats": iface_stats,
        "traceroute_hops": hops,
    }

    # 并发跑 check
    click.echo("\n🚀 并发跑 4 个 check...")

    check_fns = {
        "rogue_router": check_rogue_router,
        "loop": check_loop,
        "arp_spoof": check_arp_spoof,
        "topology": check_topology,
    }

    results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fn, ctx): name for name, fn in check_fns.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
                click.echo(f"   ✅ {name} 完成")
            except Exception as e:
                click.echo(f"   ❌ {name} 失败: {e}", err=True)
                results[name] = CheckResult(
                    name=name,
                    verdict=Verdict.NORMAL,
                    confidence=Confidence.LOW,
                    summary=f"Check 失败: {e}",
                    sub_findings=[],
                    evidence=[],
                    remediation=[],
                )

    return results


# ============================================================
# HTML 报告生成
# ============================================================

REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Lanwatch Diagnostic 报告 — {{ label }}</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "PingFang SC", sans-serif; margin: 0; padding: 40px 20px; background: #f5f5f7; color: #1d1d1f; }
  .container { max-width: 920px; margin: 0 auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.08); }
  h1 { color: #1d1d1f; border-bottom: 3px solid #0071e3; padding-bottom: 12px; margin: 0 0 16px 0; }
  h2 { color: #1d1d1f; margin-top: 32px; font-size: 20px; }
  .meta { color: #6e6e73; font-size: 13px; margin-bottom: 24px; }
  .meta strong { color: #1d1d1f; }
  .summary { padding: 20px; border-radius: 10px; font-size: 18px; font-weight: 600; margin-bottom: 24px; }
  .summary.normal { background: #e8f5e9; color: #2e7d32; border-left: 4px solid #4caf50; }
  .summary.warning { background: #fff3e0; color: #e65100; border-left: 4px solid #ff9800; }
  .summary.critical { background: #ffebee; color: #c62828; border-left: 4px solid #f44336; }
  .summary small { font-size: 13px; font-weight: normal; display: block; margin-top: 6px; opacity: 0.9; }
  .check { border: 1px solid #e0e0e0; border-radius: 10px; padding: 20px; margin: 16px 0; background: #fafafa; }
  .check-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
  .check-name { font-size: 16px; font-weight: 600; color: #1d1d1f; }
  .check-name-en { font-size: 12px; color: #6e6e73; font-weight: normal; margin-left: 8px; }
  .badge { padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
  .badge.normal { background: #4caf50; color: white; }
  .badge.warning { background: #ff9800; color: white; }
  .badge.critical { background: #f44336; color: white; }
  .check-summary { font-size: 14px; color: #424245; margin-bottom: 12px; }
  .finding { padding: 10px 14px; margin: 6px 0; border-radius: 6px; font-size: 13px; }
  .finding.normal { background: #f5f5f7; color: #1d1d1f; }
  .finding.warning { background: #fff8e1; color: #e65100; }
  .finding.critical { background: #ffebee; color: #c62828; }
  .finding strong { color: #1d1d1f; margin-right: 4px; }
  .evidence { background: white; padding: 12px 16px; margin-top: 12px; border-radius: 6px; font-size: 13px; border-left: 3px solid #9c27b0; }
  .evidence strong { color: #6a1b9a; }
  .evidence code { background: #f5f5f7; padding: 1px 6px; border-radius: 3px; font-size: 12px; color: #1d1d1f; }
  .remediation { background: #e3f2fd; padding: 14px 16px; margin-top: 12px; border-radius: 6px; font-size: 13px; border-left: 3px solid #1976d2; }
  .remediation strong { color: #0d47a1; display: block; margin-bottom: 6px; }
  .remediation ul { margin: 4px 0 0 0; padding-left: 20px; }
  .remediation li { margin: 3px 0; }
  .next-steps { background: linear-gradient(135deg, #f3e5f5 0%, #e8eaf6 100%); padding: 20px; border-radius: 10px; margin-top: 24px; border-left: 4px solid #9c27b0; }
  .next-steps h3 { margin: 0 0 10px 0; color: #4a148c; }
  .footer { margin-top: 40px; text-align: center; color: #6e6e73; font-size: 11px; }
  .privacy-note { background: #fff9c4; padding: 10px 14px; border-radius: 6px; font-size: 12px; color: #f57f17; margin-bottom: 20px; border-left: 3px solid #fbc02d; }
</style>
</head>
<body>
<div class="container">

<h1>🌐 Lanwatch Diagnostic 报告</h1>

<div class="privacy-note">
  🔒 <strong>隐私声明</strong>：本报告基于本机被动观察（ARP 表 / 路由表 / DNS / traceroute），
  不含主动扫描、不上传服务端。MAC 信息仅供现场工程师参考。
</div>

<div class="meta">
  标签：<strong>{{ label }}</strong> ·
  {% if company %}公司：<strong>{{ company_hash }}</strong>（hash）·{% endif %}
  时间：<strong>{{ timestamp }}</strong> ·
  版本：<strong>passive MVP v0.1</strong>
</div>

<div class="summary {{ overall_verdict }}">
  总评：{{ overall_verdict|upper }}{% if overall_confidence %}（{{ overall_confidence }} 置信度）{% endif %}
  <small>{{ overall_summary }}</small>
</div>

{% for check in checks %}
<div class="check">
  <div class="check-header">
    <div>
      <span class="check-name">{{ check.label_zh }}</span>
      <span class="check-name-en">{{ check.name }}</span>
    </div>
    <span class="badge {{ check.verdict }}">{{ check.verdict }}</span>
  </div>
  <div class="check-summary">{{ check.summary }}</div>

  {% for f in check.sub_findings %}
  <div class="finding {{ f.verdict }}">
    <strong>{{ f.dimension }}:</strong> {{ f.note }}
  </div>
  {% endfor %}

  {% if check.evidence %}
  <div class="evidence">
    <strong>📌 证据：</strong>
    {% for e in check.evidence %}
    <div style="margin-top: 8px;">
      <strong>{{ e.title }}</strong>
      <ul style="margin: 4px 0; padding-left: 20px;">
      {% for item in e.items %}
        <li><code>{{ item }}</code></li>
      {% endfor %}
      </ul>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  {% if check.remediation %}
  <div class="remediation">
    <strong>💡 建议措施：</strong>
    <ul>
    {% for r in check.remediation %}
      <li>{{ r }}</li>
    {% endfor %}
    </ul>
  </div>
  {% endif %}
</div>
{% endfor %}

<div class="next-steps">
  <h3>📦 下一步建议</h3>
  <p>本报告为<strong>被动观察版</strong>（v0.1），仅基于本机状态，不含主动扫描维度。</p>
  <p>如发现网络问题，建议装 <strong>lanwatch_agent</strong> SaaS 持续监控，自动告警类似事件，不再需要每次上门诊断。</p>
  <p>主动扫描版本（DHCP probe、ARP 子网扫描）需客户授权后单独运行——请联系超哥申请。</p>
</div>

<div class="footer">
  Generated by lanwatch-diagnostic passive MVP v0.1 · {{ timestamp }} · 本地保存，未上传
</div>

</div>
</body>
</html>
"""


def render_report(results: dict, label: str, company: str) -> str:
    """渲染 HTML 报告"""

    # 综合总评
    verdicts = [r.verdict for r in results.values()]
    if Verdict.CRITICAL in verdicts:
        overall = Verdict.CRITICAL
    elif Verdict.WARNING in verdicts:
        overall = Verdict.WARNING
    else:
        overall = Verdict.NORMAL

    # 最高置信度
    confidences = [r.confidence for r in results.values()]
    overall_conf = max(confidences, key=lambda c: ["low", "medium", "high"].index(c.value))

    # 综合摘要
    critical_checks = [r for r in results.values() if r.verdict == Verdict.CRITICAL]
    warning_checks = [r for r in results.values() if r.verdict == Verdict.WARNING]
    if critical_checks:
        overall_summary = f"严重问题：{', '.join(c.name for c in critical_checks)} 报警"
    elif warning_checks:
        overall_summary = f"警告：{', '.join(c.name for c in warning_checks)} 报警"
    else:
        overall_summary = "被动观察未发现明显异常"

    # Check 标签映射
    label_zh = {
        "rogue_router": "私接小路由检测",
        "loop": "网络环路检测",
        "arp_spoof": "ARP 欺骗检测",
        "topology": "组网结构检测",
    }

    checks_data = []
    for name in ["rogue_router", "loop", "arp_spoof", "topology"]:
        r = results.get(name)
        if r:
            checks_data.append({
                "name": r.name,
                "label_zh": label_zh.get(r.name, r.name),
                "verdict": r.verdict.value,
                "summary": r.summary,
                "sub_findings": [{"dimension": f.dimension, "verdict": f.verdict.value, "note": f.note} for f in r.sub_findings],
                "evidence": [{"title": e.title, "items": [str(item) for item in e.items]} for e in r.evidence],
                "remediation": r.remediation,
            })

    # 公司名 hash
    company_hash = hashlib.md5(company.encode()).hexdigest()[:8] if company else "anon"

    tmpl = jinja2.Template(REPORT_TEMPLATE)
    return tmpl.render(
        label=label,
        company=company,
        company_hash=company_hash,
        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        overall_verdict=overall.value,
        overall_confidence=overall_conf.value,
        overall_summary=overall_summary,
        checks=checks_data,
    )


# ============================================================
# CLI
# ============================================================

import socket  # 用于 get_local_ip_and_mask


@click.command()
@click.option("--label", required=True, help="报告标签（如 '正常对照' / '喊慢客户A'）")
@click.option("--company", default="", help="公司标识（可选，存报告时 hash 处理）")
@click.option("--output-dir", default="~/lanwatch_agent/diagnostic/local_runs/", help="报告输出目录")
@click.option("--dry-run", is_flag=True, help="只采集数据不渲染报告")
@click.option("--no-traceroute", is_flag=True, help="跳过 traceroute（macOS 无 sudo 时可能 hang）")
def main(label, company, output_dir, dry_run, no_traceroute):
    """Lanwatch Diagnostic 被动观察版 — 不主动扫描，只读本机状态"""

    output_dir = os.path.expanduser(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Banner
    click.echo("=" * 60)
    click.echo("🌐 Lanwatch Diagnostic 被动观察 MVP v0.1")
    click.echo("=" * 60)
    click.echo(f"  标签：{label}")
    if company:
        click.echo(f"  公司：{company}（报告中仅显示 hash）")
    click.echo(f"  输出：{output_dir}")
    click.echo("")

    # 跑 checks
    start_time = datetime.datetime.now()
    results = run_all_checks(label, no_traceroute)
    duration = (datetime.datetime.now() - start_time).total_seconds()

    # 输出每个 check 的判定
    click.echo("\n" + "=" * 60)
    click.echo("📋 判定结果")
    click.echo("=" * 60)

    label_zh = {
        "rogue_router": "私接小路由",
        "loop": "网络环路",
        "arp_spoof": "ARP 欺骗",
        "topology": "组网结构",
    }

    for name in ["rogue_router", "loop", "arp_spoof", "topology"]:
        r = results.get(name)
        if r:
            click.echo(f"\n  [{r.verdict.value.upper():8}] {label_zh.get(name, name)} ({name})")
            click.echo(f"           {r.summary}")
            for f in r.sub_findings:
                icon = "✅" if f.verdict == Verdict.NORMAL else ("⚠️ " if f.verdict == Verdict.WARNING else "🔴")
                click.echo(f"           {icon} {f.dimension}: {f.note}")

    click.echo(f"\n⏱️  总耗时 {duration:.1f} 秒")

    # Dry run
    if dry_run:
        click.echo("\n🛑 Dry run 模式，未生成报告")
        return

    # 渲染 HTML 报告
    click.echo("\n📄 渲染 HTML 报告...")
    html = render_report(results, label, company)

    # 文件名（带 hash）
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    company_slug = hashlib.md5(company.encode()).hexdigest()[:6] if company else "anon"
    safe_label = re.sub(r"[^\w\u4e00-\u9fff-]", "_", label)
    filename = f"{timestamp}.{safe_label}.{company_slug}.html"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    click.echo(f"   ✅ 报告已保存：{filepath}")
    click.echo(f"\n🎯 提示：用浏览器打开查看")

    # 总体建议
    verdicts = [r.verdict for r in results.values()]
    if Verdict.CRITICAL in verdicts:
        click.echo("\n🚨 检测到严重问题——建议立即排查")
    elif Verdict.WARNING in verdicts:
        click.echo("\n⚠️  检测到警告——建议进一步排查")
    else:
        click.echo("\n✅ 被动观察未发现明显异常")


if __name__ == "__main__":
    main()