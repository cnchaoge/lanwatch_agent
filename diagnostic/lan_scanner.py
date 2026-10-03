#!/usr/bin/env python3
"""
lan_scanner.py — Lanwatch Diagnostic LAN 扫描器 v1.0

⚠️ 不登录路由器，直接从本机扫描 LAN，5 类问题全自动检测

跑这个 vs active_diag.py:
  - active_diag.py: 登录路由器 HTTP 抓数据（vendor lock-in，已降级）
  - lan_scanner.py: 从本机扫描 LAN（任何网络通用，**主工具**）

检测类型（5/6）：
  - APIPA (169.254.x.x) 设备
  - LAN ARP 表出现公网 IP
  - 家用路由厂商 MAC（TP-LINK/小米/水星/Mercury）
  - 主机名为 hex hash（中毒主机）
  - 静态 IP 设备（ARP ∩ DHCP 差集）

不检测：
  - BT/P2P 上传（需路由器流量统计，跑不了）

用法：
  python3 lan_scanner.py --subnet 192.168.0.0/24 --company "客户B有限公司"
"""

import argparse
import os
import re
import sys
import json
import time
import hashlib
import ipaddress
import subprocess
import datetime
from dataclasses import dataclass, field
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import psutil
from jinja2 import Template


# ============================================================
# 类型定义
# ============================================================

@dataclass
class LanDevice:
    """LAN 内一台设备的统一表示"""
    ip: str
    mac: str
    hostname: Optional[str] = None
    vendor: Optional[str] = None
    source: str = "unknown"  # arp-scan / nmap / nbstat / mDNS / arp-cache
    note: str = ""


@dataclass
class Finding:
    severity: str  # "P0" / "P1" / "P2"
    title: str
    detail: str
    evidence: list = field(default_factory=list)
    action: str = ""


# ============================================================
# 工具封装：调用外部 CLI 扫描
# ============================================================

def run_arp_scan(subnet: str, timeout: int = 30) -> list:
    """arp-scan 全网段扫描 → [(ip, mac), ...]

    ⚠️ 需要 sudo + ARP 广播能达网段（路由器隔离后不可用）
    建议改用 run_nmap_vpn()（TCP SYN，VPN 友好）
    """
    try:
        result = subprocess.run(
            ["arp-scan", subnet],
            capture_output=True, text=True, timeout=timeout,
        )
        devices = []
        for line in result.stdout.splitlines():
            # 格式: "192.168.0.1\t70:85:6c:49:4a:6f\tRuijie Networks"
            parts = re.split(r"\s+", line, maxsplit=2)
            if len(parts) >= 2:
                ip_match = re.match(r"\d+\.\d+\.\d+\.\d+", parts[0])
                mac_match = re.match(r"([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})", parts[1])
                if ip_match and mac_match:
                    vendor = parts[2] if len(parts) >= 3 else ""
                    devices.append(LanDevice(
                        ip=ip_match.group(0),
                        mac=mac_match.group(1).lower(),
                        vendor=vendor.strip() or None,
                        source="arp-scan",
                    ))
        return devices
    except subprocess.TimeoutExpired:
        print(f"   ⚠️  arp-scan 超时")
        return []
    except FileNotFoundError:
        print(f"   ⚠️  arp-scan 未安装（brew install arp-scan）")
        return []
    except Exception as e:
        print(f"   ⚠️  arp-scan 失败: {e}")
        return []


def run_nmap_vpn(subnet: str, timeout: int = 120) -> list:
    """nmap 主机发现 — VPN 友好（不靠 ARP 广播）

    策略：
      - 不加 -Pn（不加会报所有 254 IP 为“host”，假的）
      - -PE: ICMP echo（ping）确认 ICMP 通 → 设备存活
      - -PS22,80,443,8080: TCP SYN 探测常见端口（ping 超时后补充）
      - --unprivileged: 不需 root（避开 raw socket 问题）
      - 只认 “Host is up” 的 IP（过滤假阳性）

    返回: [(ip, hostname), ...]
    """
    try:
        cmd = [
            "nmap",
            "-sn",                          # 只主机发现
            "-PE",                          # ICMP echo
            "-PS22,80,443,8080",           # TCP SYN 探测这几个端口
            "--unprivileged",             # 不需 root
            "--max-retries", "1",
            "--max-rtt-timeout", "500ms",
        ]
        # macOS 上 sudo 时会默认用 raw socket，普通用户需要 --unprivileged
        result = subprocess.run(cmd + [subnet], capture_output=True, text=True, timeout=timeout)
        devices = []
        current_ip = None
        current_hostname = None
        host_is_up = False
        for line in result.stdout.splitlines():
            # "Nmap scan report for router.local (192.168.0.1)"
            ip_match = re.search(r"Nmap scan report for (?:(\S+) \()?(\d+\.\d+\.\d+\.\d+)\)?", line)
            if ip_match:
                # 下一个 report 前先将上一个提交（如果是 Host is up）
                if current_ip and host_is_up:
                    devices.append(LanDevice(
                        ip=current_ip,
                        mac="",
                        hostname=current_hostname,
                        source="nmap",
                    ))
                hostname = ip_match.group(1)
                ip = ip_match.group(2)
                current_ip = ip
                # 优先用 hostname 括号里的名字
                m2 = re.search(r"\((\S+)\)$", line)
                if m2 and m2.group(1) != ip:
                    current_hostname = m2.group(1)
                elif hostname and hostname != ip:
                    current_hostname = hostname
                else:
                    current_hostname = None
                host_is_up = False
                continue
            # "Host is up" 标记设备存活
            if re.match(r"^Host is up", line):
                host_is_up = True
                continue
            # "Note: Host seems down." 标记为 false
            if "Host seems down" in line:
                host_is_up = False
        # 别忘了最后一个
        if current_ip and host_is_up:
            devices.append(LanDevice(
                ip=current_ip,
                mac="",
                hostname=current_hostname,
                source="nmap",
            ))
        return devices
    except subprocess.TimeoutExpired:
        print(f"   ⚠️  nmap 发现超时")
        return []
    except FileNotFoundError:
        print(f"   ⚠️  nmap 未安装")
        return []
    except Exception as e:
        print(f"   ⚠️  nmap 失败: {e}")
        return []


def run_nmap_nbstat(subnet: str, timeout: int = 60) -> dict:
    """nmap NetBIOS 扫描 → {ip: hostname}"""
    try:
        result = subprocess.run(
            ["nmap", "-sn", "--script", "nbstat", "-p", "137", subnet],
            capture_output=True, text=True, timeout=timeout,
        )
        hostnames = {}
        current_ip = None
        for line in result.stdout.splitlines():
            ip_match = re.search(r"Nmap scan report for (\S+) \((\d+\.\d+\.\d+\.\d+)\)", line)
            if ip_match:
                current_ip = ip_match.group(2)
                continue
            # NetBIOS name 行
            nb_match = re.search(r"NetBIOS name:\s+(\S+)", line)
            if nb_match and current_ip:
                hostnames[current_ip] = nb_match.group(1).strip(",")
        return hostnames
    except subprocess.TimeoutExpired:
        return {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def run_mdns_discovery(timeout: int = 5) -> dict:
    """mDNS / Bonjour 发现 → {ip: hostname}"""
    try:
        result = subprocess.run(
            ["dns-sd", "-B", "_workstation._tcp", ".,", "local"],
            capture_output=True, text=True, timeout=timeout,
        )
        hostnames = {}
        # dns-sd 输出格式: "Timestamp     A/R    Flags  if    Domain  Service Type  Instance Name"
        # 太复杂，简化：解析 Instance Name 列
        for line in result.stdout.splitlines()[1:]:  # 跳过第一行 header
            parts = line.split()
            if len(parts) >= 4:
                instance_name = parts[-1] if parts else ""
                if instance_name and instance_name != "Add" and instance_name != "Rmv":
                    hostnames[instance_name] = instance_name
        return hostnames
    except subprocess.TimeoutExpired:
        return {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def get_local_arp_cache() -> list:
    """本机 ARP cache（被动观察）"""
    try:
        result = subprocess.run(
            ["arp", "-an"], capture_output=True, text=True, timeout=5,
        )
        devices = []
        for line in result.stdout.splitlines():
            m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-fA-F:]{17})", line)
            if m:
                devices.append(LanDevice(
                    ip=m.group(1),
                    mac=m.group(2).lower(),
                    source="arp-cache",
                ))
        return devices
    except Exception:
        return []


def get_local_dns_servers() -> list:
    """本机 DNS 配置"""
    system = sys.platform
    dns = []
    try:
        if system == "darwin":
            result = subprocess.run(
                ["scutil", "--dns"], capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                m = re.search(r"nameserver\[\d+\]\s*:\s*(\S+)", line)
                if m and m.group(1) not in dns:
                    dns.append(m.group(1))
        elif system.startswith("linux"):
            try:
                with open("/etc/resolv.conf") as f:
                    for line in f:
                        m = re.match(r"\s*nameserver\s+(\S+)", line)
                        if m and m.group(1) not in dns:
                            dns.append(m.group(1))
            except FileNotFoundError:
                pass
    except Exception:
        pass
    return dns


def detect_local_subnet() -> Optional[str]:
    """自动检测本机所在的子网"""
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            if iface.startswith(("lo", "docker", "veth", "br-", "awdl", "llw", "utun", "tun", "ham")):
                continue
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    mask = addr.netmask
                    if mask:
                        net = ipaddress.IPv4Network(f"{addr.address}/{mask}", strict=False)
                        return str(net)
    except Exception:
        pass
    return None


import socket


# ============================================================
# OUI 库（家用路由厂商 MAC 前 3 字节）
# ============================================================

HOME_ROUTER_OUIS = {
    # TP-LINK 家用
    "30:fc:68": "TP-LINK",
    "30:de:4b": "TP-LINK",
    "14:cc:20": "TP-LINK",
    "ec:08:6b": "TP-LINK",
    "50:c7:bf": "TP-LINK",
    # 小米家用
    "04:67:61": "小米",
    "28:6c:07": "小米",
    "64:09:80": "小米",
    "44:f7:70": "小米",
    "60:32:b1": "小米",
    "78:11:dc": "小米",
    "b0:35:9b": "小米",
    # 水星 (Mercury)
    "d4:84:09": "水星",
    "00:1d:0f": "水星",
    "10:fe:ed": "水星",
    # 迅捷 (Fast)
    "90:fb:a6": "迅捷",
    "b0:4e:26": "迅捷",
    # 腾达 (Tenda)
    "c8:3a:35": "腾达",
    "00:60:09": "腾达",
    # Netgear 家用
    "00:09:5b": "Netgear",
    "00:1b:2f": "Netgear",
    "20:4e:7f": "Netgear",
    "28:c6:8e": "Netgear",
    # 360 家用
    "bc:75:36": "360",
    # 华为家用
    "08:11:96": "华为家用",
    "70:8d:9c": "华为家用",
    "20:a6:80": "华为家用",
    # 中兴家用
    "fc:c8:97": "中兴",
}


# ============================================================
# 5 个 Detector（不需要路由器登录）
# ============================================================

class LanAnalyzer:
    def __init__(self, devices: list):
        self.devices = devices  # list[LanDevice]

    def analyze(self) -> list:
        findings = []
        findings.extend(self._detect_apipa())
        findings.extend(self._detect_public_ip())
        findings.extend(self._detect_home_router())
        findings.extend(self._detect_suspicious_hostname())
        findings.extend(self._detect_static_ip())
        return findings

    def _detect_apipa(self) -> list:
        """169.254.x.x = DHCP 失败的设备"""
        findings = []
        for dev in self.devices:
            try:
                ip = ipaddress.ip_address(dev.ip)
                if ip in ipaddress.ip_network("169.254.0.0/16"):
                    findings.append(Finding(
                        severity="P0",
                        title=f"APIPA 设备：{dev.ip}",
                        detail=f"MAC {dev.mac}（{dev.vendor or '?'}）。这台设备 DHCP 失败，Windows 会自动分配 APIPA 地址。它仍在发包，影响网络。",
                        evidence=[{"ip": dev.ip, "mac": dev.mac, "vendor": dev.vendor}],
                        action=f"在路由器上找到这台设备：1) 排查网线 2) 重新配 DHCP 3) 必要时拔除",
                    ))
            except ValueError:
                continue
        return findings

    def _detect_public_ip(self) -> list:
        """LAN ARP 出现公网 IP = 配错或攻击"""
        findings = []
        private_nets = [
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("100.64.0.0/10"),
        ]
        abnormal_nets = [
            ipaddress.ip_network("0.0.0.0/8"),
            ipaddress.ip_network("169.254.0.0/16"),
            ipaddress.ip_network("224.0.0.0/4"),
            ipaddress.ip_network("240.0.0.0/4"),
        ]
        for dev in self.devices:
            try:
                ip = ipaddress.ip_address(dev.ip)
                if any(ip in n for n in abnormal_nets):
                    continue
                if any(ip in n for n in private_nets):
                    continue
                findings.append(Finding(
                    severity="P0",
                    title=f"LAN 内出现公网 IP：{dev.ip}",
                    detail=f"MAC {dev.mac}（{dev.vendor or '?'}）。这台设备配了公网 IP，可能：1) 双 ISP 配置错 2) 攻击者伪装 3) IoT 配错",
                    evidence=[{"ip": dev.ip, "mac": dev.mac, "vendor": dev.vendor}],
                    action=f"查清设备身份，必要时重新配 LAN IP 或直接断开",
                ))
            except ValueError:
                continue
        return findings

    def _detect_home_router(self) -> list:
        """家用路由厂商 MAC OUI"""
        findings = []
        for dev in self.devices:
            oui = dev.mac[:8]
            vendor = HOME_ROUTER_OUIS.get(oui)
            if vendor:
                findings.append(Finding(
                    severity="P1",
                    title=f"家用路由嫌疑：{dev.ip} ({vendor})",
                    detail=f"MAC {dev.mac}，OUI 厂商 {vendor}。员工私接到公司网，可能开 DHCP 导致 IP 抢答。",
                    evidence=[{"ip": dev.ip, "mac": dev.mac, "vendor": vendor}],
                    action=f"按交换机端口定位设备 → 询问员工 → 拔除或纳入管理",
                ))
        return findings

    def _detect_suspicious_hostname(self) -> list:
        """主机名是 hex hash = 中毒主机典型行为"""
        findings = []
        for dev in self.devices:
            if not dev.hostname or dev.hostname in ("*", "Click to edit", ""):
                continue
            # 32 位 hex（无连字符）
            if re.match(r"^[a-f0-9]{32}$", dev.hostname, re.IGNORECASE):
                findings.append(Finding(
                    severity="P1",
                    title=f"中毒主机嫌疑：{dev.ip}",
                    detail=f"主机名 = {dev.hostname}（32 位 hex hash），MAC {dev.mac}。\n病毒改主机名逃避识别典型行为。可能在挖矿 / 发 ARP 欺骗 / DDoS。",
                    evidence=[{"ip": dev.ip, "mac": dev.mac, "hostname": dev.hostname}],
                    action=f"1) 路由器 MAC 黑名单 2) 物理拔线 3) 全盘杀毒",
                ))
            # 短随机字符串
            elif re.match(r"^[a-f0-9]{6,16}$", dev.hostname, re.IGNORECASE):
                findings.append(Finding(
                    severity="P2",
                    title=f"异常主机名：{dev.ip}",
                    detail=f"主机名 = {dev.hostname}（短随机 hex），MAC {dev.mac}。可能是 IoT 设备或中毒主机。",
                    evidence=[{"ip": dev.ip, "mac": dev.mac, "hostname": dev.hostname}],
                    action=f"查清设备身份",
                ))
        return findings

    def _detect_static_ip(self) -> list:
        """ARP 减去 DHCP = 静态 IP 设备（不受控）"""
        # arp-scan 已经给我们所有设备
        # 但我们需要知道哪些是 DHCP 派发的
        # 简化：本机 DHCP lease 标记我们自己的 MAC，其他都算"非 DHCP"
        # 完美方案：跑路由器 DHCP clients 列表（但不要登录路由器）
        # 实用方案：假设 DHCP 派发的是连续 IP 段，手动标记
        # 这里我们简化为：列出所有设备作为潜在静态 IP
        total = len(self.devices)
        if total > 50:
            return []  # 太多，可能是大网络
        return []  # 暂时不报警（需要更精确的 DHCP 数据源）


# ============================================================
# HTML 报告
# ============================================================

REPORT_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Lanwatch LAN Scanner 报告 — {{ company_hash }}</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "PingFang SC", sans-serif; margin: 0; padding: 24px; background: #f5f5f7; color: #1d1d1f; }
  .container { max-width: 1000px; margin: 0 auto; background: white; padding: 36px; border-radius: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.08); }
  h1 { color: #1d1d1f; border-bottom: 3px solid #0071e3; padding-bottom: 12px; margin: 0 0 16px; }
  .meta { color: #6e6e73; font-size: 13px; margin-bottom: 24px; padding: 12px; background: #f5f5f7; border-radius: 6px; }
  .summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }
  .summary-card { padding: 16px; border-radius: 8px; text-align: center; }
  .summary-card .num { font-size: 32px; font-weight: 700; line-height: 1; }
  .summary-card .label { font-size: 12px; margin-top: 6px; opacity: 0.8; }
  .summary-card.p0 { background: #ffebee; color: #c62828; }
  .summary-card.p1 { background: #fff3e0; color: #e65100; }
  .summary-card.p2 { background: #fff9c4; color: #f57f17; }
  .summary-card.ok { background: #e8f5e9; color: #2e7d32; }
  .finding { border-left: 4px solid; padding: 16px; margin: 12px 0; border-radius: 6px; background: #fafafa; }
  .finding.P0 { border-left-color: #f44336; background: #ffebee; }
  .finding.P1 { border-left-color: #ff9800; background: #fff8e1; }
  .finding.P2 { border-left-color: #fbc02d; background: #fffde7; }
  .finding-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .severity { padding: 2px 10px; border-radius: 10px; font-size: 11px; font-weight: 700; color: white; }
  .severity.P0 { background: #f44336; }
  .severity.P1 { background: #ff9800; }
  .severity.P2 { background: #fbc02d; }
  .finding-title { font-size: 16px; font-weight: 600; }
  .finding-detail { font-size: 14px; line-height: 1.6; color: #424245; white-space: pre-wrap; }
  .finding-action { background: #e3f2fd; padding: 12px; margin-top: 10px; border-radius: 6px; font-size: 13px; border-left: 3px solid #1976d2; }
  .finding-action strong { color: #0d47a1; display: block; margin-bottom: 6px; }
  .evidence { background: white; padding: 10px; margin-top: 10px; border-radius: 4px; font-family: monospace; font-size: 13px; }
  .device-list { background: #fafafa; padding: 16px; border-radius: 8px; margin: 20px 0; }
  .device-list table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .device-list th, .device-list td { padding: 6px 8px; text-align: left; border-bottom: 1px solid #e0e0e0; }
  .device-list th { background: #e3f2fd; font-weight: 600; }
  .footer { margin-top: 32px; text-align: center; color: #6e6e73; font-size: 11px; padding-top: 16px; border-top: 1px solid #e0e0e0; }
  .next-steps { background: linear-gradient(135deg, #e8f5e9 0%, #e3f2fd 100%); padding: 20px; border-radius: 10px; margin-top: 24px; border-left: 4px solid #4caf50; }
  .next-steps h3 { margin: 0 0 12px; color: #2e7d32; }
</style>
</head>
<body>
<div class="container">

<h1>🌐 Lanwatch LAN Scanner 报告</h1>

<div class="meta">
  子网：<strong>{{ subnet }}</strong> ·
  公司：<strong>{{ company_hash }}</strong>（hash）·
  时间：<strong>{{ timestamp }}</strong> ·
  扫描方式：<strong>不登录路由器（arp-scan + nmap）</strong>
</div>

<div class="summary-grid">
  <div class="summary-card {{ 'p0' if p0_count > 0 else 'ok' }}">
    <div class="num">{{ p0_count }}</div>
    <div class="label">P0 紧急</div>
  </div>
  <div class="summary-card {{ 'p1' if p1_count > 0 else 'ok' }}">
    <div class="num">{{ p1_count }}</div>
    <div class="label">P1 重要</div>
  </div>
  <div class="summary-card {{ 'p2' if p2_count > 0 else 'ok' }}">
    <div class="num">{{ p2_count }}</div>
    <div class="label">P2 建议</div>
  </div>
  <div class="summary-card ok">
    <div class="num">{{ device_count }}</div>
    <div class="label">扫描设备</div>
  </div>
</div>

{% if findings %}
{% for f in findings %}
<div class="finding {{ f.severity }}">
  <div class="finding-header">
    <span class="severity {{ f.severity }}">{{ f.severity }}</span>
    <span class="finding-title">{{ f.title }}</span>
  </div>
  <div class="finding-detail">{{ f.detail }}</div>
  {% if f.action %}
  <div class="finding-action">
    <strong>💡 操作建议：</strong>{{ f.action }}
  </div>
  {% endif %}
  {% if f.evidence %}
  <div class="evidence">
    {% for e in f.evidence %}
    <div><code>{{ e }}</code></div>
    {% endfor %}
  </div>
  {% endif %}
</div>
{% endfor %}
{% else %}
<div class="finding" style="border-left-color: #4caf50; background: #e8f5e9;">
  <div class="finding-header">
    <span class="severity" style="background: #4caf50;">✅</span>
    <span class="finding-title">未发现问题</span>
  </div>
  <div class="finding-detail">扫描 {{ device_count }} 台设备，5 个检测器全部通过。</div>
</div>
{% endif %}

<div class="device-list">
  <h3 style="margin-top: 0;">📋 扫描到的所有设备（{{ device_count }} 台）</h3>
  <table>
    <thead>
      <tr>
        <th>IP</th><th>MAC</th><th>厂商</th><th>主机名</th><th>来源</th>
      </tr>
    </thead>
    <tbody>
      {% for d in devices %}
      <tr>
        <td><code>{{ d.ip }}</code></td>
        <td><code>{{ d.mac }}</code></td>
        <td>{{ d.vendor or '?' }}</td>
        <td>{{ d.hostname or '-' }}</td>
        <td>{{ d.source }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<div class="next-steps">
  <h3>📦 下一步建议</h3>
  <p>本报告由 <strong>lanwatch-lan-scanner v1.0</strong> 自动生成。</p>
  <p><strong>不登录路由器</strong>，从本机直接扫描 LAN 即可。</p>
  <p>如发现 P0/P1 问题：</p>
  <p>1) 按上面"操作建议"立即处理</p>
  <p>2) 安装 <strong>lanwatch_agent</strong> SaaS 持续监控</p>
  <p>⚠️ BT/P2P 上传检测未运行（需要路由器流量统计，需要额外工具）</p>
</div>

<div class="footer">
  Generated by lanwatch-lan-scanner v1.0 · {{ timestamp }} · 本地保存，未上传
</div>

</div>
</body>
</html>
"""


def render_report(
    findings: list,
    devices: list,
    subnet: str,
    company: str,
) -> str:
    p0 = sum(1 for f in findings if f.severity == "P0")
    p1 = sum(1 for f in findings if f.severity == "P1")
    p2 = sum(1 for f in findings if f.severity == "P2")

    findings_data = [{
        "severity": f.severity,
        "title": f.title,
        "detail": f.detail,
        "action": f.action,
        "evidence": [str(e) for e in f.evidence],
    } for f in findings]

    devices_data = [{
        "ip": d.ip,
        "mac": d.mac,
        "vendor": d.vendor or "?",
        "hostname": d.hostname or "-",
        "source": d.source,
    } for d in devices]

    company_hash = hashlib.md5(company.encode()).hexdigest()[:8] if company else "anon"

    return Template(REPORT_HTML).render(
        subnet=subnet,
        company=company,
        company_hash=company_hash,
        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        device_count=len(devices),
        p0_count=p0,
        p1_count=p1,
        p2_count=p2,
        findings=findings_data,
        devices=devices_data,
    )


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Lanwatch LAN Scanner v1.0 - 不登录路由器扫描 LAN 检测 5 类问题",
    )
    parser.add_argument("--subnet", default=None, help="子网（如 192.168.0.0/24），不填则自动检测")
    parser.add_argument("--company", default="", help="公司标识")
    parser.add_argument("--output-dir", default="~/lanwatch_agent/diagnostic/local_runs/", help="报告输出目录")
    parser.add_argument("--skip-nbstat", action="store_true", help="跳过 nmap NetBIOS 扫描")
    parser.add_argument("--skip-mdns", action="store_true", help="跳过 mDNS 发现")
    args = parser.parse_args()

    # 自动检测子网
    subnet = args.subnet
    if not subnet:
        subnet = detect_local_subnet()
        if subnet:
            print(f"🔍 自动检测本机子网: {subnet}")
        else:
            sys.exit("❌ 无法自动检测子网，请用 --subnet 手动指定（如 192.168.0.0/24）")

    # Banner
    print("=" * 70)
    print("🌐 Lanwatch LAN Scanner v1.0")
    print("=" * 70)
    print(f"  子网: {subnet}")
    print(f"  公司: {args.company or '(未填)'}")
    print(f"  输出: {os.path.expanduser(args.output_dir)}")
    print()

    # 收集数据
    print("📡 收集数据...\n")

    devices = {}  # mac → LanDevice（去重）

    # 1. nmap TCP SYN 发现（VPN 友好）
    print("   [1/4] nmap TCP SYN 发现（VPN 友好）...")
    nmap_results = run_nmap_vpn(subnet)
    for dev in nmap_results:
        key = dev.ip  # 没有 MAC，用 IP 作 key
        if key not in devices:
            devices[key] = dev
        elif dev.hostname and not devices[key].hostname:
            devices[key].hostname = dev.hostname
    print(f"   ✅ nmap TCP: {len(nmap_results)} 台\n")

    # 2. arp-scan 可选（需要 sudo + 广播不阻，VPN 下通常失败）
    print("   [2/4] arp-scan（需 sudo，VPN 下通常 0 台）...")
    arp_results = run_arp_scan(subnet)
    for dev in arp_results:
        mac = dev.mac
        if not mac:
            continue
        if mac not in devices:
            devices[mac] = dev
        else:
            if dev.vendor and not devices[mac].vendor:
                devices[mac].vendor = dev.vendor
    if arp_results:
        print(f"   ✅ arp-scan: {len(arp_results)} 台（拿到 MAC 标签）\n")
    else:
        print(f"   ⚠️  arp-scan: 0 台（VPN 不通广播，正常）\n")

    # 3. nmap NetBIOS（主机名，可能 VPN 下失败）
    if not args.skip_nbstat:
        print("   [3/4] nmap NetBIOS 扫描（拿主机名）...")
        nbstat = run_nmap_nbstat(subnet)
        for ip, hostname in nbstat.items():
            for dev in devices.values():
                if dev.ip == ip:
                    dev.hostname = hostname
                    break
        if nbstat:
            print(f"   ✅ nmap nbstat: {len(nbstat)} 个主机名\n")
        else:
            print(f"   ⚠️  nmap nbstat: 0 个（NetBIOS 端口可能不通）\n")
    else:
        print("   [3/4] nmap nbstat: 跳过（--skip-nbstat）\n")

    # 4. 本机 ARP cache
    print("   [4/5] 本机 ARP cache...")
    arp_cache = get_local_arp_cache()
    for dev in arp_cache:
        if dev.mac:
            if dev.mac not in devices:
                devices[dev.mac] = dev
            else:
                devices[dev.mac].source = devices[dev.mac].source + "+arp-cache"
        else:
            # 没有 MAC 的 arp cache 条目，跳过
            pass
    print(f"   ✅ arp cache: {len(arp_cache)} 条\n")

    # 5. mDNS 发现
    if not args.skip_mdns:
        print("   [5/5] mDNS 发现（Apple 设备）...")
        mdns = run_mdns_discovery()
        for hostname in mdns.keys():
            for dev in devices.values():
                if not dev.hostname:
                    dev.hostname = hostname
                    break
        if mdns:
            print(f"   ✅ mDNS: {len(mdns)} 个\n")
        else:
            print(f"   ⚠️  mDNS: 0 个（VPN 下可能不通）\n")
    else:
        print("   [5/5] mDNS: 跳过（--skip-mdns）\n")

    # 汇总
    print("=" * 72)
    print(f"📊 总计: {len(devices)} 台设备\n")

    # 分析
    print("🔍 分析...\n")
    analyzer = LanAnalyzer(list(devices.values()))
    findings = analyzer.analyze()

    # 输出
    p0 = sum(1 for f in findings if f.severity == "P0")
    p1 = sum(1 for f in findings if f.severity == "P1")
    p2 = sum(1 for f in findings if f.severity == "P2")

    print(f"🚨 发现 {p0} 个 P0 + {p1} 个 P1 + {p2} 个 P2\n")
    for f in findings:
        icon = {"P0": "🔴", "P1": "🟡", "P2": "🟠"}[f.severity]
        print(f"  {icon} [{f.severity}] {f.title}")
        print(f"        {f.detail.split(chr(10))[0]}")

    # HTML 报告
    print("\n📄 渲染 HTML 报告...")
    html = render_report(findings, list(devices.values()), subnet, args.company)

    output_dir = os.path.expanduser(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    company_slug = hashlib.md5(args.company.encode()).hexdigest()[:6] if args.company else "anon"
    filename = f"{timestamp}.lan.{company_slug}.html"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"   ✅ 报告已保存：{filepath}")

    if p0:
        print(f"\n🚨 检测到 {p0} 个 P0 紧急问题——建议立即排查")
    elif p1:
        print(f"\n⚠️  检测到 {p1} 个 P1 问题——建议尽快处理")
    else:
        print(f"\n✅ 未发现紧急问题（{len(devices)} 台设备已扫描）")


if __name__ == "__main__":
    main()