#!/usr/bin/env python3
"""
active_diag.py — Lanwatch Diagnostic 主动版 v1.0

⚠️ 主动问路由器（需要 router 管理后台账号，env var 提供）

用法:
  ROUTER_ADMIN_USER=admin ROUTER_ADMIN_PASS=xxx python3 active_diag.py \\
    --router 192.168.0.254 --company "客户B有限公司"

输出:
  ~/lanwatch_agent/diagnostic/local_runs/{date}.active.{company_hash}.html

🔍 自动检测的6 类问题:
  - APIPA (169.254.x.x) 设备
  - 公网 IP 误配
  - 家用路由厂商 MAC（TP-LINK/小米/水星/Mercury/Tenda）
  - 主机名为 hex hash（中毒主机）
  - 静态 IP 设备（ARP-DHCP 差集 = 不受控）
  - P2P/BT 上传异常

🛡️ 设计哲学:
  - 只读操作（GET/POST login only），不修改路由器配置
  - 凭证通过 env var 提供，不进聊天/日志
  - 失败优雅降级（某个 page 抓不到就跳过该类检测）
"""

import os
import re
import sys
import json
import time
import argparse
import hashlib
import warnings
import datetime
import ipaddress
import subprocess
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# 关闭 SSL 警告（路由器自签证书常见）
warnings.filterwarnings("ignore", message="Unverified HTTPS request")


# ============================================================
# 数据结构
# ============================================================

@dataclass
class DHCPClient:
    hostname: str
    ip: str
    mac: str


@dataclass
class ARPEntry:
    ip: str
    mac: str
    type: str  # "动态" / "静态"
    iface: str = ""


@dataclass
class FlowStat:
    ip: str
    down_mbps: float
    up_mbps: float


@dataclass
class Finding:
    severity: str  # "P0" / "P1" / "P2"
    title: str
    detail: str
    evidence: list = field(default_factory=list)
    action: str = ""


# ============================================================
# 路由器 scraper（LuCI 框架 + 锐捷 EG105G-V2 测试）
# ============================================================

class RouterScraper:
    """通用 LuCI 路由器 scraper，锐捷 EG105G-V2 测试通过

    失败策略：每个抓取步骤独立 try/except，失败不阻塞其他检测
    """

    # 多种登录 URL 候选（适配不同 LuCI 版本）
    LOGIN_PATHS = [
        "/cgi-bin/luci/;stok=/login",
        "/cgi-bin/luci/admin/alone",
        "/cgi-bin/luci",
        "/login.cgi",
        "/",
    ]

    def __init__(self, router_ip: str, username: str, password: str, timeout: int = 10):
        self.router_ip = router_ip
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) lanwatch-diag/1.0",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        self.csrf_token: Optional[str] = None
        self.base_url = f"http://{router_ip}"

    def _extract_csrf(self, text: str, url: str = "", headers: dict = None) -> Optional[str]:
        """从 HTML / URL / Location header 中提取 CSRF token"""
        # 1. Location header (302 重定向)
        if headers:
            location = headers.get("Location", "") + headers.get("location", "")
            m = re.search(r'stok=([a-f0-9]+)', location, re.IGNORECASE)
            if m:
                return m.group(1)
            m = re.search(r'[;?]stok=([a-f0-9]+)', location, re.IGNORECASE)
            if m:
                return m.group(1)

        # 2. URL 本身 (e.g., ;stok=XXX)
        combined = text + url
        for pattern in [
            r'stok=([a-f0-9]{16,})',
            r'stok["\s:=]+([a-f0-9]{16,})',
            r'csrf[_-]?token["\s:=]+([a-f0-9]{16,})',
            r'["\']token["\']\s*[:=]\s*["\']([a-f0-9]{16,})["\']',
        ]:
            m = re.search(pattern, combined, re.IGNORECASE)
            if m:
                return m.group(1)
        return None

    def _looks_like_login_page(self, html: str) -> bool:
        """检测响应是否是登录页面（而非真页面）"""
        if not html:
            return True
        html_lower = html.lower()
        # 登录页特征
        login_keywords = ["登录", "login", "password", "用户名", "请输入", "user name", "请登陆"]
        keyword_hits = sum(1 for kw in login_keywords if kw in html_lower)
        # 如果登录关键字 ≥ 2 个且页面较短，很可能是登录页
        if keyword_hits >= 2 and len(html) < 5000:
            return True
        return False

    def login(self) -> bool:
        """POST 登录获取 session cookie + CSRF token"""
        # 先 GET 一次拿初始 cookie + token
        for path in self.LOGIN_PATHS:
            try:
                r = self.session.get(urljoin(self.base_url, path), timeout=self.timeout, allow_redirects=True)
                token = self._extract_csrf(r.text, r.url, dict(r.headers))
                if token:
                    self.csrf_token = token
                    break
            except requests.RequestException:
                continue

        # 尝试登录（多种数据格式）
        login_payloads = [
            {"username": self.username, "password": self.password},
            {"admin_username": self.username, "admin_password": self.password},
            {"user": self.username, "pass": self.password},
        ]

        for path in self.LOGIN_PATHS:
            for payload in login_payloads:
                try:
                    r = self.session.post(
                        urljoin(self.base_url, path),
                        data=payload,
                        timeout=self.timeout,
                        allow_redirects=False,
                    )
                    # 302 重定向或 Set-Cookie 通常意味着登录成功
                    if r.status_code in (200, 302):
                        if "Set-Cookie" in r.headers or "auth" in r.text.lower() or r.status_code == 302:
                            # 提取 token（从 Location header 最重要）
                            token = self._extract_csrf(r.text, r.url, dict(r.headers))
                            if token:
                                self.csrf_token = token
                            return True
                except requests.RequestException:
                    continue
        return False

    def _get(self, path: str) -> Optional[str]:
        """GET 页面：先尝试带 CSRF token，失败则不带

        LuCI 路由器 CSRF token 通常在 URL 路径中（`;stok=XXX`）或查询参数（`?stok=XXX`）
        """
        # 候选 URL 格式（按优先级）
        urls_to_try = []

        base_url = urljoin(self.base_url, path)
        urls_to_try.append(base_url)  # 无 CSRF

        if self.csrf_token and "stok=" not in path and ";" not in path:
            # LuCI 风格：;stok=XXX 在路径中
            sep = ";" if "?" not in path else "&"
            urls_to_try.append(f"{base_url}{sep}stok={self.csrf_token}")
            # 查询参数风格
            sep_q = "?" if "?" not in path else "&"
            urls_to_try.append(f"{base_url}{sep_q}stok={self.csrf_token}")

        for url in urls_to_try:
            try:
                r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                if r.status_code == 200 and r.text and not self._looks_like_login_page(r.text):
                    # 顺便更新 CSRF token（如果变了）
                    new_token = self._extract_csrf(r.text, r.url, dict(r.headers))
                    if new_token:
                        self.csrf_token = new_token
                    return r.text
            except requests.RequestException:
                continue
        return None

    # ----- 硬编码 URL 候选（auto-discovery 失败时的 fallback） -----
    HARDCODED_ARP_URLS = [
        "/admin/alone/network/arp",
        "/cgi-bin/luci/admin/alone/network/arp",
        "/network/arp",
        "/arp_table",
        "/status/arp",
        "/admin/alone/network/network_lan",
        "/admin/alone/network/network_lan?showArp=true",
    ]
    HARDCODED_DHCP_URLS = [
        "/admin/alone/network/dhcp",
        "/cgi-bin/luci/admin/alone/network/dhcp",
        "/network/dhcp",
        "/dhcp_clients",
        "/services/dhcp",
        "/admin/alone/services/dhcp",
    ]
    HARDCODED_FLOW_URLS = [
        "/admin/alone/network/network_wan?showTopo=true",
        "/cgi-bin/luci/admin/alone/network/network_wan",
        "/network/network_wan",
        "/admin/alone/network/network_wan",
        "/traffic_stats",
        "/status/traffic",
        "/admin/alone/status/traffic",
    ]

    # ----- URL 自动发现 -----
    def discover_pages(self, debug: bool = False) -> dict:
        """登录后扫描所有内部链接，按关键字分类

        返回: {"arp": [url, ...], "dhcp": [url, ...], "flow": [url, ...], "other": [url, ...]}
        """
        pages = {"arp": [], "dhcp": [], "flow": [], "other": []}

        # 多个候选主页 URL（鲁棒性）
        home_paths = [
            "/admin/alone/network/network_lan",
            "/admin/alone",
            "/admin/alone/network/network_wan",
            "/admin/alone/network",
            "/",
            "/index.html",
        ]

        all_links = set()
        for path in home_paths:
            html = self._get(path)
            if not html:
                continue
            try:
                soup = BeautifulSoup(html, "html.parser")
                # 抓所有 a 标签
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if not href or href.startswith("#") or href.startswith("javascript:"):
                        continue
                    # 转绝对路径
                    if href.startswith("/"):
                        all_links.add(href)
                    elif href.startswith("http"):
                        full = href.replace(self.base_url, "").replace("http://", "").replace("https://", "")
                        if "/" in full:
                            all_links.add("/" + full.split("/", 1)[1])
                # 抓菜单项（li/onclick 等也可能含 URL）
                for elem in soup.find_all(["li", "div"], onclick=True):
                    m = re.search(r"['\"]([^'\"]*\.html?[^'\"]*)['\"]", elem.get("onclick", ""))
                    if m and m.group(1).startswith("/"):
                        all_links.add(m.group(1))
            except Exception:
                continue
            if all_links:
                break  # 找到一个有链接的主页就够了

        # 分类
        for url in all_links:
            url_lower = url.lower()
            url_no_ext = re.sub(r"\.(html?|json|cgi)$", "", url_lower)
            # ARP：arp / neighbor / 地址解析
            if re.search(r"(arp|neighbour|地址解析|邻居表)", url_no_ext):
                pages["arp"].append(url)
            # DHCP：dhcp / lease / client / 客户端
            elif re.search(r"(dhcp|lease|client|客户端|地址分配)", url_no_ext):
                pages["dhcp"].append(url)
            # Flow：flow / traffic / stat / wan / monitor / 流量
            elif re.search(r"(flow|traffic|stat|wan|monitor|流量|排行|上行|下行)", url_no_ext):
                pages["flow"].append(url)
            else:
                pages["other"].append(url)

        if debug:
            print(f"   🔍 [debug] 发现链接 {len(all_links)} 个:")
            for url in sorted(all_links)[:30]:
                marker = ""
                if url in pages["arp"]: marker = " ← ARP"
                elif url in pages["dhcp"]: marker = " ← DHCP"
                elif url in pages["flow"]: marker = " ← Flow"
                print(f"     - {url}{marker}")

        return pages

    # ----- 内容驱动页面分类（URL 猜错时的终极 fallback）-----
    def _classify_by_content(self, urls: list, debug: bool = False) -> dict:
        """下载每个 URL，按内容关键字识别页面类型（ARP/DHCP/Flow）

        启发式：
          - ARP 页面：含 ≥3 个 MAC 地址 + "arp/neighbor/地址解析" 关键字
          - DHCP 页面：含 "客户端/hostname/地址分配" 关键字
          - Flow 页面：含 "Mbps/MB/下行/上行/流量/排行" 关键字

        返回: {"arp": [urls], "dhcp": [urls], "flow": [urls]}
        """
        classified = {"arp": [], "dhcp": [], "flow": []}

        # 限制最多抓 20 个 URL避免太慢
        urls_to_check = urls[:20]
        if debug:
            print(f"   🔍 [debug] 内容扫描 {len(urls_to_check)} 个 URL...")

        for url in urls_to_check:
            html = self._get(url)
            if not html:
                continue

            html_lower = html.lower()

            # ARP 启发式：多个 MAC 地址 + 关键字
            mac_count = len(re.findall(r"[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}", html))
            has_arp_kw = any(kw in html_lower for kw in ["arp", "neighbor", "地址解析", "邻居表"])
            if mac_count >= 3 and has_arp_kw:
                classified["arp"].append(url)
                if debug:
                    print(f"     ✅ ARP match: {url} (MAC count: {mac_count})")

            # DHCP 启发式：客户端/hostname 关键字
            has_dhcp_kw = any(kw in html_lower for kw in ["dhcp", "客户端", "hostname", "地址分配", "租用"])
            has_table = "<table" in html_lower or "mac" in html_lower
            if has_dhcp_kw and has_table:
                classified["dhcp"].append(url)
                if debug:
                    print(f"     ✅ DHCP match: {url}")

            # Flow 启发式：Mbps/下行/上行/流量关键字 + 数字
            has_flow_kw = any(kw in html_lower for kw in ["mbps", "kbps", "gbps", "下行", "上行", "流量", "排行", "速率"])
            has_ips = len(re.findall(r"\d+\.\d+\.\d+\.\d+", html)) >= 3
            if has_flow_kw and has_ips:
                classified["flow"].append(url)
                if debug:
                    print(f"     ✅ Flow match: {url}")

        return classified

    # ----- ARP via SSH（锐捷 VRP / Huawei 平台）-----
    def get_arp_via_ssh(self, debug: bool = False) -> list:
        """SSH 进路由器跑 'display arp' 命令拿 ARP 表

        锐捷 EG105G-V2 是 Huawei VRP 平台，默认 SSH=ON (端口 22)
        输出格式:
          IP ADDRESS    MAC ADDRESS    EXPIRE(M) TYPE INTERFACE
          192.168.0.1   70-85-6c-49-4a-6f  20  D  Eth0/0/0
        """
        try:
            import paramiko
        except ImportError:
            if debug:
                print("   ⚠️  paramiko 未安装，跳过 SSH (pip3 install paramiko)")
            return []

        if debug:
            print(f"   🔍 [debug] 尝试 SSH 'display arp'...")

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                self.router_ip,
                username=self.username,
                password=self.password,
                timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False,
            )

            # 锐捷 VRP / Huawei 命令
            commands = ["display arp", "display arp all", "show arp"]
            output = ""
            for cmd in commands:
                try:
                    stdin, stdout, stderr = client.exec_command(cmd, timeout=self.timeout)
                    out = stdout.read().decode('utf-8', errors='ignore')
                    if out and 'IP' in out:  # 有 IP 关键字说明拿到了
                        output = out
                        if debug:
                            print(f"   ✅ SSH 命令成功：{cmd}")
                        break
                except Exception:
                    continue
            client.close()

            # 解析 display arp 输出
            entries = []
            for line in output.splitlines():
                ip_match = re.match(r'^\s*(\d+\.\d+\.\d+\.\d+)', line)
                if not ip_match:
                    continue
                ip = ip_match.group(1)
                # MAC 可能是 70-85-6c-49-4a-6f 或 aa:bb:cc:dd:ee:ff 格式
                mac_match = re.search(
                    r'([0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}'
                    r'[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2})',
                    line
                )
                if mac_match:
                    mac = mac_match.group(1).replace('-', ':').lower()
                    if mac not in ('ff:ff:ff:ff:ff:ff', '00:00:00:00:00:00'):
                        entries.append(ARPEntry(ip=ip, mac=mac, type='动态'))

            if debug:
                print(f"   ✅ SSH ARP 抓取成功：{len(entries)} 条")
            return entries

        except paramiko.AuthenticationException:
            if debug:
                print("   ⚠️  SSH 认证失败（密码错误？）")
            return []
        except paramiko.SSHException as e:
            if debug:
                print(f"   ⚠️  SSH 错误: {e}")
            return []
        except Exception as e:
            if debug:
                print(f"   ⚠️  SSH 异常: {e}")
            return []

    # ----- ARP/DHCP/Flow via Browser (Playwright) -----
    def fetch_pages_via_browser(self, target_paths: list, debug: bool = False) -> dict:
        """用 Playwright 浏览器自动登录路由器 + 抓多个页面

        返回: {path: html_str}，供另存 + 后续解析
        优点：完全处理 CSRF/cookies/JavaScript/redirects/隐藏表单字段
        缺点：~150MB Chromium，首次启动 ~3s
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("   ⚠️  playwright 未安装，跳过浏览器模式 (pip3 install playwright)")
            return {}

        save_dir = os.path.expanduser('~/lanwatch_agent/diagnostic/local_runs/raw/')
        os.makedirs(save_dir, exist_ok=True)

        result = {}
        print(f"   🌐 启动浏览器 (Playwright + Chromium)...")

        with sync_playwright() as p:
            # 默认无头模式（保证能跑），加 --visible flag 改为可见模式
            try:
                browser = p.chromium.launch(
                    headless=not getattr(self, 'visible', False),
                    args=['--no-sandbox', '--disable-dev-shm-usage'],
                )
            except Exception as launch_err:
                print(f"   ❌ Chromium 启动失败: {launch_err}")
                print(f"   💡 试试加 --headless flag，或检查 Chrome 路径")
                return result
            try:
                # 忽略 HTTPS 自签证书错误（路由器普遍用自签）
                context = browser.new_context(
                    viewport={'width': 1280, 'height': 800},
                    ignore_https_errors=True,
                )
                page = context.new_page()

                # ====== Step 1: 自动探测协议（锐捷 HTTPS，少数 HTTP）======
                base_url = None
                for protocol in ['https', 'http']:
                    try:
                        test_url = f'{protocol}://{self.router_ip}/'
                        resp = page.goto(test_url, timeout=self.timeout * 1000, wait_until='domcontentloaded')
                        content = page.content()
                        # 如果拿到真实 HTML（含 input 或 login 关键字）则采用
                        if '<input' in content.lower() or 'login' in content.lower() or len(content) > 500:
                            base_url = test_url.rstrip('/')
                            print(f"   ✅ 协议: {protocol.upper()} （路由器管理后台可达）")
                            break
                        else:
                            if debug:
                                print(f"   ⚠️  {protocol.upper()} 返回空，试试下一个协议")
                    except Exception as e:
                        if debug:
                            print(f"   ⚠️  {protocol.upper()} 连接失败: {e}")
                        continue

                if not base_url:
                    print(f"   ❌ HTTPS 和 HTTP 都不可达")
                    print(f"   💡 可能原因：1) 路由器 IP 不对 2) 路由器宕机 3) 防火墙阻隔")
                    return result

                # 重新加载以确保拿到完整页面
                page.goto(base_url + '/', timeout=self.timeout * 1000, wait_until='networkidle')
                print(f"   📄 登录页加载完成（{base_url}）")

                # 保存登录页 HTML（即使登录失败也能诊断）
                login_html = page.content()
                login_path = f'{save_dir}/{self.router_ip}_login.html'
                with open(login_path, 'w', encoding='utf-8') as f:
                    f.write(login_html)

                # ====== Step 2: 自动找用户名/密码/提交按钮 ======
                username_selectors = [
                    'input[name="luci_username"]',
                    'input[name="username"]',
                    'input[name="admin_username"]',
                    'input[name="user"]',
                    'input[type="text"]:visible',
                ]
                password_selectors = [
                    'input[name="luci_password"]',
                    'input[name="password"]',
                    'input[name="admin_password"]',
                    'input[name="pass"]',
                    'input[type="password"]',
                ]
                submit_selectors = [
                    'button[type="submit"]',
                    'input[type="submit"]',
                    'button:has-text("登录")',
                    'button:has-text("登 录")',
                    'button:has-text("Login")',
                    'a:has-text("登录")',
                ]

                # 找用户名（可选 — 锐捷 EG105G-V2 等只有 password 字段）
                username_sel = None
                for sel in username_selectors:
                    if page.locator(sel).count() > 0:
                        username_sel = sel
                        break

                if username_sel:
                    page.fill(username_sel, self.username)
                    if debug:
                        print(f"   ✅ 已填用户名（{username_sel}）")
                else:
                    print(f"   ℹ️  该路由器无 username 字段（只要求密码）")

                # 找密码
                password_sel = None
                for sel in password_selectors:
                    if page.locator(sel).count() > 0:
                        password_sel = sel
                        break

                if not password_sel:
                    print(f"   ❌ 找不到密码输入框")
                    print(f"   💾 登录页 HTML 已存: {login_path}")
                    return result

                page.fill(password_sel, self.password)
                if debug:
                    print(f"   ✅ 已填密码（{password_sel}）")

                # 锐捷路由要求先勾选用户协议才能点登录
                try:
                    page.locator('#readAgreement').click(timeout=2000)
                    if debug:
                        print(f"   ✅ 点击用户协议")
                except Exception:
                    pass

                # 等提交按钮从 disabled 变 enabled
                try:
                    page.wait_for_selector('#login:not(.disabled)', timeout=5000)
                except Exception:
                    print(f"   ⚠️  提交按钮仍为 disabled（密码错误或协议未勾选）")

                # 点提交
                submit_clicked = False
                for sel in submit_selectors:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click()
                        submit_clicked = True
                        if debug:
                            print(f"   ✅ 点击提交（{sel}）")
                        break
                if not submit_clicked:
                    page.keyboard.press('Enter')
                    if debug:
                        print(f"   ⏎  按 Enter 提交")

                # ====== Step 3: 等登录完成 ======
                # 点击提交后等异步登录（按钮会显示 "Logging..."）
                try:
                    submit_btn = page.locator('#login:not(.disabled)')
                    if submit_btn.count() > 0:
                        submit_btn.first.click()
                        if debug:
                            print(f"   ✅ 点提交 #login")
                    else:
                        page.locator('#login').first.click()
                except Exception as e:
                    print(f"   ⚠️  点提交失败: {e}")

                # 等按钮恢复（“Logging...” 变回 “Log In” 或跳走）
                try:
                    page.wait_for_function(
                        "() => { const b = document.querySelector('#login'); return !b || b.innerText.trim() !== 'Logging...'; }",
                        timeout=15000,
                    )
                    if debug:
                        print(f"   ✅ 登录请求完成")
                except Exception:
                    print(f"   ⚠️  登录超时（15s 未完成）")

                # 等页面不在登录页（networkidle + URL 变化）
                try:
                    page.wait_for_load_state('networkidle', timeout=self.timeout * 1000)
                except Exception:
                    pass
                for _ in range(20):
                    if '/login' not in page.url.lower():
                        break
                    page.wait_for_timeout(500)

                post_login_url = page.url
                post_html = page.content()

                # 检查是否还停在登录页（登录失败）
                if 'input.post-password' in post_html or 'id="password"' in post_html:
                    print(f"   ❌ 登录失败：仍停留在登录页")
                    post_path = f'{save_dir}/{self.router_ip}_login_FAILED.html'
                    with open(post_path, 'w', encoding='utf-8') as f:
                        f.write(post_html)
                    return result
                print(f"   ✅ 登录后 URL: {post_login_url[:80]}")

                # 保存登录后的页面（供诊断菜单结构）
                post_path = f'{save_dir}/{self.router_ip}_post_login.html'
                with open(post_path, 'w', encoding='utf-8') as f:
                    f.write(post_html)

                # ====== Step 4: 扫描菜单（锐捷 EG105G-V2 用 Element UI，li.el-menu-item）======
                nav_targets = {"arp": [], "dhcp": [], "flow": []}

                # 先扫所有 <a> 链接
                try:
                    for link in page.locator('a[href]').all():
                        try:
                            href = link.get_attribute('href') or ''
                            text = (link.inner_text() or '').lower()
                            if not href or href.startswith('javascript:') or href.startswith('#'):
                                continue
                            for category in ("arp", "dhcp", "flow"):
                                kws = {"arp": ["arp", "设备"], "dhcp": ["dhcp", "客户端"], "flow": ["流量", "wan", "gateway"]}[category]
                                if any(k in text for k in kws):
                                    nav_targets[category].append(("a", href))
                        except Exception:
                            continue
                except Exception:
                    pass

                # 再扫 <li> Element UI 菜单项（锐捷主框架）
                try:
                    for li in page.locator('li.el-menu-item, li[role="menuitem"]').all():
                        try:
                            title_attr = (li.get_attribute('title') or '').lower()
                            li_id = (li.get_attribute('id') or '').lower()
                            text = (li.inner_text() or '').lower()
                            for category in ("arp", "dhcp", "flow"):
                                kws = {"arp": ["device", "设备"], "dhcp": ["client", "客户端", "online"], "flow": ["gateway", "overview", "网关"]}[category]
                                if any(k in (title_attr + li_id + text) for k in kws):
                                    nav_targets[category].append(("li", None))
                                    break
                        except Exception:
                            continue
                except Exception:
                    pass

                counts = {k: len(v) for k, v in nav_targets.items()}
                print(f"   🔍 菜单发现: arp={counts['arp']} dhcp={counts['dhcp']} flow={counts['flow']}")

                # ====== Step 5: 点击菜单获取页面 ======
                for category in ("arp", "dhcp", "flow"):
                    if not nav_targets[category]:
                        continue
                    sel_type, href = nav_targets[category][0]
                    try:
                        if sel_type == "a" and href:
                            # 链接形式：goto URL
                            if href.startswith('http'):
                                url = href
                            elif href.startswith('/'):
                                base = '/'.join(post_login_url.split('/')[:3])
                                url = base + href
                            else:
                                continue
                            page.goto(url, timeout=self.timeout * 1000, wait_until='domcontentloaded')
                        else:
                            # li 菜单项：点击（Vue.js SPA 导航）
                            # 根据 category 选具体菜单
                            menu_selector = {
                                "arp": "#stepdevice",       # Devices（主表格 + IP/MAC）
                                "dhcp": "#stephome_online", # Clients（含 hostname）
                                "flow": "#stephome_overview", # Workspace（流量统计）
                            }.get(category)
                            if menu_selector:
                                page.locator(menu_selector).click(timeout=5000)
                            else:
                                # fallback: click first li
                                page.locator('li.el-menu-item').first.click(timeout=5000)

                        # 等 SPA 路由加载完成
                        try:
                            page.wait_for_load_state('networkidle', timeout=self.timeout * 1000)
                        except Exception:
                            pass
                        page.wait_for_timeout(2000)  # 给 Vue.js 渲染时间

                        html = page.content()
                        result[category] = html
                        filename = f"{save_dir}/{self.router_ip}_{category}.html"
                        with open(filename, 'w', encoding='utf-8') as f:
                            f.write(html)
                        print(f"   ✅ {category} → {len(html)} 字符 (存 {os.path.basename(filename)})")
                    except Exception as e:
                        print(f"   ❌ {category}: {e}")

            finally:
                browser.close()

        return result

    def get_arp_via_browser(self, debug: bool = False) -> list:
        """用浏览器抓 ARP 表（解析锐捷 EG105G-V2 LAN 页面）"""
        pages = self.fetch_pages_via_browser([
            '/admin/alone/network/network_lan',
            '/admin/alone/network/arp',
            '/admin/alone/network/network_lan?showArp=true',
        ], debug=debug)

        for path, html in pages.items():
            if html:
                result = self._parse_arp_html(html)
                if result:
                    if debug:
                        print(f"   ✅ Browser ARP 抓取成功（{path}，{len(result)} 条）")
                    return result

        return []

    # ----- ARP via SNMP -----
    def get_arp_via_snmp(self, community: str = None, debug: bool = False) -> list:
        """用 SNMP 抓取 ARP 表（最可靠，不需登录/CSRF/URL）

        OID: 1.3.6.1.2.1.4.22.1.2 (ipNetToMediaPhysAddress)
        macOS 装 net-snmp: brew install net-snmp
        """
        if community is None:
            community = os.environ.get("SNMP_COMMUNITY", "public")

        oid = "1.3.6.1.2.1.4.22.1.2"

        if debug:
            print(f"   🔍 [debug] 尝试 SNMP ARP 抓取 (community: {community})...")

        try:
            result = subprocess.run(
                ["snmpwalk", "-v2c", "-c", community, "-t", "5", self.router_ip, oid],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                if debug:
                    err = result.stderr[:200] if result.stderr else "N/A"
                    print(f"   ⚠️  SNMP 返回非零（可能未启用）: {err}")
                return []

            entries = []
            # 格式: iso.3.6.1.2.1.4.22.1.2.1.192.168.1.1 = Hex-STRING: aa bb cc dd ee ff
            for line in result.stdout.splitlines():
                m = re.search(r"\.(\d+\.\d+\.\d+\.\d+)\s*=\s*Hex-STRING:\s*([0-9a-fA-F ]+)", line)
                if m:
                    ip = m.group(1)
                    hex_mac = m.group(2).replace(" ", "")
                    if len(hex_mac) == 12:
                        mac = ":".join(hex_mac[i:i+2] for i in range(0, 12, 2)).lower()
                        entries.append(ARPEntry(ip=ip, mac=mac, type="动态"))
            if debug:
                print(f"   ✅ SNMP ARP 抓取成功：{len(entries)} 条")
            return entries
        except FileNotFoundError:
            if debug:
                print("   ⚠️  snmpwalk 未安装，跳过 SNMP（brew install net-snmp）")
            return []
        except subprocess.TimeoutExpired:
            if debug:
                print("   ⚠️  SNMP 超时（路由器可能未启用 SNMP）")
            return []
        except Exception as e:
            if debug:
                print(f"   ⚠️  SNMP 错误: {e}")
            return []

    # ----- ARP 表 -----
    def get_arp_table(self, debug: bool = False, snmp_community: str = None, method: str = "auto") -> list:
        """爬 ARP 表：SNMP / SSH / Browser / HTTP 四层 fallback

        method:
          - "auto"：试所有可用方法
          - "snmp"：仅 SNMP
          - "ssh"：仅 SSH
          - "web"：仅浏览器自动化
        """
        use_snmp = method in ("auto", "snmp")
        use_ssh = method in ("auto", "ssh")
        use_web = method in ("auto", "web")

        # 1. SNMP
        if use_snmp:
            print(f"   🔍 尝试 SNMP (community={snmp_community or 'public'})...")
            snmp_arp = self.get_arp_via_snmp(community=snmp_community, debug=debug)
            if snmp_arp:
                print(f"   ✅ SNMP 拿到 {len(snmp_arp)} 条")
                return snmp_arp
            print(f"   ⚠️  SNMP 无数据（路由器可能未启用 SNMP）")

        # 2. SSH
        if use_ssh:
            ssh_arp = self.get_arp_via_ssh(debug=debug)
            if ssh_arp:
                print(f"   ✅ SSH 拿到 {len(ssh_arp)} 条")
                return ssh_arp
            print(f"   ⚠️  SSH 无数据（可能端口关闭/认证失败）")

        # 3. Browser (Playwright)
        if use_web:
            print(f"   🔍 尝试浏览器自动化 (Playwright)...")
            browser_arp = self.get_arp_via_browser(debug=debug)
            if browser_arp:
                print(f"   ✅ Browser 拿到 {len(browser_arp)} 条")
                return browser_arp

        # 4. HTTP scraping（仅 auto 模式兜底）
        if method == "auto":
            print(f"   🔍 尝试 HTTP scraping...")
            discovered = self.discover_pages(debug=debug)
        else:
            discovered = {"arp": [], "dhcp": [], "flow": [], "other": []}  # 占位避免 UnboundLocalError
        arp_urls = list(discovered.get("arp", []))

        # 3. 如果链接没找到 ARP 页面，按内容扫描所有已知 URL
        if not arp_urls:
            all_urls = (discovered.get("arp", []) + discovered.get("dhcp", []) +
                        discovered.get("flow", []) + discovered.get("other", []))
            content_classified = self._classify_by_content(all_urls, debug=debug)
            arp_urls = content_classified.get("arp", [])

        # 4. 合并硬编码候选
        urls_to_try = arp_urls + self.HARDCODED_ARP_URLS

        # 5. 去重
        seen = set()
        unique_urls = []
        for u in urls_to_try:
            if u not in seen:
                seen.add(u)
                unique_urls.append(u)

        tried = []
        for path in unique_urls:
            tried.append(path)
            html = self._get(path)
            if html and ("ARP" in html or "arp" in html or "MAC" in html):
                result = self._parse_arp_html(html)
                if result:
                    if debug:
                        print(f"   ✅ ARP 抓取成功：{path} ({len(result)} 条)")
                    return result

        if debug:
            print(f"   ❌ ARP 抓取失败，尝试了 {len(tried)} 个 URL")

        return []

    def _parse_el_table(self, html: str) -> list:
        """通用 Element UI 表格解析器

        锐捷 EG105G-V2 用 Element UI，表格结构：
          <table class="el-table__body">
            <tbody>
              <tr class="el-table__row">
                <td class="el-table_X_column_Y">
                  <div class="cell">VALUE</div>
                </td>
              </tr>
            </tbody>
          </table>

        ⚠️ Element UI 会重复保存主表格数据到 fixed-left/fixed-right layout tables
           本函数只解析主表格（避开 el-table__fixed-*）

        返回: list of {column_name: text} dicts
        """
        rows = []
        seen = set()  # 去重行
        try:
            soup = BeautifulSoup(html, "html.parser")
            for table in soup.find_all("table", class_="el-table__body"):
                # 跳过 fixed layout tables
                parent_classes = []
                parent = table.parent
                while parent:
                    pc = parent.get("class", [])
                    if pc:
                        parent_classes.extend(pc)
                    parent = parent.parent
                if any("el-table__fixed" in c for c in parent_classes):
                    continue

                tbody = table.find("tbody")
                if not tbody:
                    continue
                for tr in tbody.find_all("tr", class_="el-table__row"):
                    row_data = {}
                    for td in tr.find_all("td"):
                        classes = td.get("class", [])
                        col_class = next((c for c in classes if "column" in c), "unknown")
                        cell_text = []
                        for cell_div in td.find_all("div", class_="cell"):
                            cell_text.append(cell_div.get_text(separator=" ", strip=True))
                        if not cell_text:
                            cell_text.append(td.get_text(separator=" ", strip=True))
                        row_data[col_class] = " | ".join(cell_text).strip()
                    if row_data:
                        # 去重（Element UI 有时会在同一行重复 td）
                        row_key = tuple(sorted(row_data.items()))
                        if row_key not in seen:
                            seen.add(row_key)
                            rows.append(row_data)
        except Exception as e:
            if self.debug:
                print(f"   ⚠️ _parse_el_table: {e}")
        return rows

    def _parse_arp_html(self, html: str) -> list:
        """解析设备列表（ARP 类似数据）"""
        result = []
        try:
            for row in self._parse_el_table(html):
                # 锐捷格式：列 class 含 "column_X"，内容用 | 分隔 IP / MAC
                ip = None
                mac = None
                for text in row.values():
                    ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', text)
                    mac_match = re.search(r'([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})', text)
                    if ip_match and not ip:
                        ip = ip_match.group(1)
                    if mac_match and not mac:
                        mac = mac_match.group(1).lower()
                if ip and mac:
                    result.append(ARPEntry(ip=ip, mac=mac, type="动态"))
        except Exception:
            pass
        return result

    # ----- DHCP 客户端 -----
    def get_dhcp_clients(self, debug: bool = False) -> list:
        """爬 DHCP 客户端列表：auto-discovery → content-match → 硬编码"""
        discovered = self.discover_pages(debug=debug)
        dhcp_urls = list(discovered.get("dhcp", []))

        if not dhcp_urls:
            all_urls = (discovered.get("arp", []) + discovered.get("dhcp", []) +
                        discovered.get("flow", []) + discovered.get("other", []))
            content_classified = self._classify_by_content(all_urls, debug=debug)
            dhcp_urls = content_classified.get("dhcp", [])

        urls_to_try = dhcp_urls + self.HARDCODED_DHCP_URLS

        seen = set()
        unique_urls = []
        for u in urls_to_try:
            if u not in seen:
                seen.add(u)
                unique_urls.append(u)

        tried = []
        for path in unique_urls:
            tried.append(path)
            html = self._get(path)
            if html and ("DHCP" in html or "主机" in html or "hostname" in html.lower()):
                result = self._parse_dhcp_html(html)
                if result:
                    if debug:
                        print(f"   ✅ DHCP 抓取成功：{path} ({len(result)} 条)")
                    return result

        if debug:
            print(f"   ❌ DHCP 抓取失败，尝试了 {len(tried)} 个 URL")

        return []

    def _parse_dhcp_html(self, html: str) -> list:
        """解析 Clients 页面（Element UI，含 hostname + IP + MAC）

        锐捷格式：列 10 = Username（hostname），列 13 = IP/MAC（IP | MAC）
        """
        result = []
        try:
            for row in self._parse_el_table(html):
                hostname = ""
                ip = None
                mac = None
                # 找 Username 列（通常 column_10）
                for col, text in row.items():
                    if "column_10" in col:
                        hostname = text
                    elif "column_13" in col:
                        # 拆 IP | MAC
                        parts = text.split("|")
                        for p in parts:
                            p = p.strip()
                            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', p)
                            mac_match = re.search(r'([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})', p)
                            if ip_match and not ip:
                                ip = ip_match.group(1)
                            if mac_match and not mac:
                                mac = mac_match.group(1).lower()
                # hostname 是 "Click to edit" 之类的占位符 → 当作 "*"
                if hostname.lower() in ("click to edit", ""):
                    hostname = "*"
                if ip and mac:
                    result.append(DHCPClient(hostname=hostname, ip=ip, mac=mac))
        except Exception:
            pass
        return result

    # ----- 流量统计 -----
    def get_flow_stats(self, debug: bool = False) -> list:
        """爬流量统计：auto-discovery → content-match → 硬编码"""
        discovered = self.discover_pages(debug=debug)
        flow_urls = list(discovered.get("flow", []))

        if not flow_urls:
            all_urls = (discovered.get("arp", []) + discovered.get("dhcp", []) +
                        discovered.get("flow", []) + discovered.get("other", []))
            content_classified = self._classify_by_content(all_urls, debug=debug)
            flow_urls = content_classified.get("flow", [])

        urls_to_try = flow_urls + self.HARDCODED_FLOW_URLS

        seen = set()
        unique_urls = []
        for u in urls_to_try:
            if u not in seen:
                seen.add(u)
                unique_urls.append(u)

        tried = []
        for path in unique_urls:
            tried.append(path)
            html = self._get(path)
            if html and ("Mbps" in html or "流量" in html or "下行" in html):
                result = self._parse_flow_html(html)
                if result:
                    if debug:
                        print(f"   ✅ Flow 抓取成功：{path} ({len(result)} 条)")
                    return result

        if debug:
            print(f"   ❌ Flow 抓取失败，尝试了 {len(tried)} 个 URL")

        return []

    def _parse_flow_html(self, html: str) -> list:
        """解析流量统计（Element UI）

        Gateway 页面会含 per-IP 流量表（如有）；如页面只是配置表则返回空
        """
        result = []
        try:
            for row in self._parse_el_table(html):
                ip = None
                down = 0.0
                up = 0.0
                for text in row.values():
                    ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', text)
                    if ip_match and not ip:
                        ip = ip_match.group(1)
                    # 找 "XXXMbps" 或 "XXX Gbps"
                    for m in re.finditer(r'([\d.]+)\s*(Mbps|Gbps|Kbps|bps)', text, re.IGNORECASE):
                        val = float(m.group(1))
                        unit = m.group(2).lower()
                        if unit == "gbps":
                            val *= 1000
                        elif unit == "kbps":
                            val /= 1000
                        if down == 0.0:
                            down = val
                        elif up == 0.0:
                            up = val
                if ip and (down > 0 or up > 0):
                    result.append(FlowStat(ip=ip, down_mbps=down, up_mbps=up))
        except Exception:
            pass
        return result


# ============================================================
# 分析器：把数据交叉对比，输出 P0/P1/P2
# ============================================================

class NetworkAnalyzer:
    """网络问题分析器"""

    # 家用消费级路由厂商 MAC OUI（节选，完整版可以扩展）
    HOME_ROUTER_OUI = {
        "30:fc:68": "TP-LINK",
        "30:de:4b": "TP-LINK",
        "14:cc:20": "TP-LINK",
        "04:67:61": "小米",
        "28:6c:07": "小米",
        "64:09:80": "小米",
        "44:f7:70": "小米",
        "d4:84:09": "水星 (Mercury)",
        "00:1d:0f": "水星 (Mercury)",
        "90:fb:a6": "迅捷 (Fast)",
        "c8:3a:35": "腾达 (Tenda)",
        "00:09:5b": "Netgear",
        "bc:75:36": "360",
        "08:11:96": "华为家用",
        "70:8d:9c": "华为家用",
    }

    # 异常段
    ABNORMAL_NETS = [
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),  # APIPA / link-local
        ipaddress.ip_network("224.0.0.0/4"),     # multicast
        ipaddress.ip_network("240.0.0.0/4"),     # reserved
    ]

    # 私有段（RFC1918 + CGNAT）
    PRIVATE_NETS = [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("100.64.0.0/10"),
    ]

    def analyze(
        self,
        arp: list,
        dhcp: list,
        flow: list,
    ) -> list:
        findings = []

        findings.extend(self._detect_apipa(arp))
        findings.extend(self._detect_public_ip(arp))
        findings.extend(self._detect_home_router(arp))
        findings.extend(self._detect_static_only(arp, dhcp))
        findings.extend(self._detect_suspicious_hostname(dhcp))
        findings.extend(self._detect_bt_upload(flow))

        return findings

    def _detect_apipa(self, arp: list) -> list:
        """APIPA（169.254.x.x）= DHCP 失败的设备在乱发包"""
        findings = []
        for entry in arp:
            try:
                ip = ipaddress.ip_address(entry.ip)
                if ip in ipaddress.ip_network("169.254.0.0/16"):
                    findings.append(Finding(
                        severity="P0",
                        title=f"APIPA 设备：{entry.ip}",
                        detail=f"MAC {entry.mac}。这台机器 DHCP 失败，Windows 会自动分配 APIPA 地址。它仍在发包，影响网络。",
                        evidence=[{"ip": entry.ip, "mac": entry.mac, "type": entry.type}],
                        action=f"在路由器上找到这台设备：1) 排查网线 / 3) 重新配 DHCP / 4) 必要时物理拔除",
                    ))
            except ValueError:
                continue
        return findings

    def _detect_public_ip(self, arp: list) -> list:
        """ARP 里出现公网 IP = 配错或攻击"""
        findings = []
        for entry in arp:
            try:
                ip = ipaddress.ip_address(entry.ip)
                # 是私有段则跳过
                if any(ip in n for n in self.PRIVATE_NETS):
                    continue
                # 是异常段则跳过（multicast 等）
                if any(ip in n for n in self.ABNORMAL_NETS):
                    continue
                # 是公网 IP
                findings.append(Finding(
                    severity="P0",
                    title=f"LAN ARP 表出现公网 IP：{entry.ip}",
                    detail=f"MAC {entry.mac}。这台设备配了公网 IP，可能：1) 双 ISP 配置错 / 2) 攻击者伪装 / 3) IoT 设备配错",
                    evidence=[{"ip": entry.ip, "mac": entry.mac, "type": entry.type}],
                    action=f"查清设备身份，可能需要重新配 LAN IP 或直接断开",
                ))
            except ValueError:
                continue
        return findings

    def _detect_home_router(self, arp: list) -> list:
        """家用路由厂商 MAC OUI"""
        findings = []
        for entry in arp:
            oui = entry.mac[:8]
            vendor = self.HOME_ROUTER_OUI.get(oui)
            if vendor:
                findings.append(Finding(
                    severity="P1",
                    title=f"家用路由嫌疑：{entry.ip} ({vendor})",
                    detail=f"MAC {entry.mac}，OUI 厂商 {vendor}。员工私接到公司网，可能开 DHCP 导致 IP 抢答。",
                    evidence=[{"ip": entry.ip, "mac": entry.mac, "vendor": vendor}],
                    action=f"按交换机端口定位设备 → 询问员工 → 拔除或纳入管理",
                ))
        return findings

    def _detect_static_only(self, arp: list, dhcp: list) -> list:
        """静态 IP 设备（ARP - DHCP）= 不受控"""
        dhcp_ips = {c.ip for c in dhcp}
        static_devices = [e for e in arp if e.ip not in dhcp_ips]
        if static_devices:
            # 排除 APIPA 和公网 IP（已单独报警）
            real_static = []
            for e in static_devices:
                try:
                    ip = ipaddress.ip_address(e.ip)
                    if any(ip in n for n in self.ABNORMAL_NETS):
                        continue
                    if not any(ip in n for n in self.PRIVATE_NETS):
                        continue
                    real_static.append(e)
                except ValueError:
                    continue

            if real_static:
                findings = [Finding(
                    severity="P1",
                    title=f"{len(real_static)} 个静态 IP 设备（不在 DHCP 管控内）",
                    detail=f"ARP 表共 {len(arp)} 条，DHCP 客户端 {len(dhcp)} 个，差集 {len(real_static)} 个。\n\n这意味着有 {len(real_static)} 台设备绕过 DHCP 管控——可能是合法服务器，也可能是员工私自接入。",
                    evidence=[{"ip": e.ip, "mac": e.mac} for e in real_static[:20]],
                    action=f"1) 路由器开 ARP 防护 + 绑定白名单\n2) 逐台登记这些设备\n3) 不在白名单的直接断网",
                )]
                return findings
        return []

    def _detect_suspicious_hostname(self, dhcp: list) -> list:
        """主机名是 32 位 hex = 中毒主机典型行为"""
        findings = []
        for client in dhcp:
            # 32 位 hex hash 模式（不带连字符）
            if re.match(r"^[a-f0-9]{32}$", client.hostname):
                findings.append(Finding(
                    severity="P1",
                    title=f"中毒主机嫌疑：{client.ip}",
                    detail=f"主机名 = {client.hostname}（32位 hex hash），MAC {client.mac}。\n\n病毒改主机名逃避识别典型行为。可能在挖矿 / 发 ARP 欺骗 / DDoS。",
                    evidence=[{"ip": client.ip, "mac": client.mac, "hostname": client.hostname}],
                    action=f"1) 路由器 MAC 黑名单\n2) 物理拔线\n3) Malwarebytes / 卡巴斯基全盘扫描",
                ))
            # 短随机字符串（如 1678dfb3f）
            elif re.match(r"^[a-f0-9]{6,12}$", client.hostname) and "*" not in client.hostname:
                findings.append(Finding(
                    severity="P2",
                    title=f"异常主机名：{client.ip}",
                    detail=f"主机名 = {client.hostname}（短随机 hex），MAC {client.mac}。可能是 IoT 设备或中毒主机。",
                    evidence=[{"ip": client.ip, "mac": client.mac, "hostname": client.hostname}],
                    action=f"查清设备身份，确认是否合法 IoT 设备",
                ))
        return findings

    def _detect_bt_upload(self, flow: list) -> list:
        """BT/P2P 上传异常检测

        启发式：单设备上行 > 200Mbps + 上行/下行比例 > 0.3（典型 BT 特征）
        """
        findings = []
        for stat in flow:
            if stat.up_mbps < 200:
                continue
            ratio = stat.up_mbps / max(stat.down_mbps, 1)
            if ratio > 0.3 or stat.up_mbps > 500:
                findings.append(Finding(
                    severity="P1",
                    title=f"P2P/BT 上传异常：{stat.ip}",
                    detail=f"上行 {stat.up_mbps:.1f} Mbps / 下行 {stat.down_mbps:.1f} Mbps（上行/下行比 {ratio:.2f}）。\n\nBT/PT 下载典型特征，疯狂消耗上行带宽。",
                    evidence=[{"ip": stat.ip, "down_mbps": stat.down_mbps, "up_mbps": stat.up_mbps, "ratio": round(ratio, 2)}],
                    action=f"1) 找这台机器\n2) 路由器 QoS 限速 P2P 上行（建议 < 50 Mbps）\n3) 或直接封禁 P2P 应用",
                ))
        return findings


# ============================================================
# HTML 报告生成
# ============================================================

REPORT_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Lanwatch Active Diagnostic — {{ company_hash }}</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "PingFang SC", sans-serif; margin: 0; padding: 24px; background: #f5f5f7; color: #1d1d1f; }
  .container { max-width: 1000px; margin: 0 auto; background: white; padding: 36px; border-radius: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.08); }
  h1 { color: #1d1d1f; border-bottom: 3px solid #0071e3; padding-bottom: 12px; margin: 0 0 16px; }
  .meta { color: #6e6e73; font-size: 13px; margin-bottom: 24px; padding: 12px; background: #f5f5f7; border-radius: 6px; }
  .meta strong { color: #1d1d1f; }
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
  .finding-action strong { color: #0d47a1; }
  .evidence { background: white; padding: 10px; margin-top: 10px; border-radius: 4px; font-family: monospace; font-size: 12px; max-height: 200px; overflow-y: auto; }
  .evidence code { background: #f5f5f7; padding: 1px 6px; border-radius: 3px; }
  .footer { margin-top: 32px; text-align: center; color: #6e6e73; font-size: 11px; padding-top: 16px; border-top: 1px solid #e0e0e0; }
  .next-steps { background: linear-gradient(135deg, #f3e5f5 0%, #e8eaf6 100%); padding: 20px; border-radius: 10px; margin-top: 24px; border-left: 4px solid #9c27b0; }
  .next-steps h3 { margin: 0 0 12px; color: #4a148c; }
  .next-steps p { margin: 6px 0; font-size: 14px; }
</style>
</head>
<body>
<div class="container">

<h1>🌐 Lanwatch Active Diagnostic — 客户诊断报告</h1>

<div class="meta">
  路由器：<strong>{{ router }}</strong> ·
  公司：<strong>{{ company_hash }}</strong>（hash）·
  时间：<strong>{{ timestamp }}</strong> ·
  数据：<strong>{{ arp_count }} ARP</strong> · <strong>{{ dhcp_count }} DHCP</strong> · <strong>{{ flow_count }} Flow</strong> ·
  差集：<strong>{{ static_count }} 静态设备</strong>
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
    <div class="num">{{ ok }}</div>
    <div class="label">健康</div>
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
    <strong>💡 操作建议：</strong><br>{{ f.action }}
  </div>
  {% endif %}
  {% if f.evidence %}
  <div class="evidence">
    <strong>证据：</strong>
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
  <div class="finding-detail">路由器配置健康，未检测到私接路由 / APIPA / 中毒主机 / P2P 异常等常见问题。</div>
</div>
{% endif %}

<div class="next-steps">
  <h3>📦 下一步建议</h3>
  <p>本报告由 <strong>lanwatch-active-diag v1.0</strong> 自动生成。</p>
  <p>如发现 P0/P1 问题：</p>
  <p>1) 按上面"操作建议"立即处理</p>
  <p>2) 安装 <strong>lanwatch_agent</strong> SaaS 持续监控（自动告警，无需每次现场）</p>
  <p>3) 联系超哥：<code>超哥</code></p>
</div>

<div class="footer">
  Generated by lanwatch-active-diag v1.0 · {{ timestamp }} · 本地保存，未上传
</div>

</div>
</body>
</html>
"""


def render_report(
    findings: list,
    company: str,
    router: str,
    arp_count: int,
    dhcp_count: int,
    flow_count: int,
    static_count: int,
) -> str:
    """渲染 HTML 报告"""
    from jinja2 import Template

    p0 = [f for f in findings if f.severity == "P0"]
    p1 = [f for f in findings if f.severity == "P1"]
    p2 = [f for f in findings if f.severity == "P2"]
    ok = 1 if not findings else 0

    # 格式化证据（dict 转字符串）
    findings_data = []
    for f in findings:
        ev_str = []
        for e in f.evidence:
            if isinstance(e, dict):
                ev_str.append(" | ".join(f"{k}={v}" for k, v in e.items()))
            else:
                ev_str.append(str(e))
        findings_data.append({
            "severity": f.severity,
            "title": f.title,
            "detail": f.detail,
            "action": f.action,
            "evidence": ev_str,
        })

    company_hash = hashlib.md5(company.encode()).hexdigest()[:8] if company else "anon"

    return Template(REPORT_HTML).render(
        company=company,
        company_hash=company_hash,
        router=router,
        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        arp_count=arp_count,
        dhcp_count=dhcp_count,
        flow_count=flow_count,
        static_count=static_count,
        p0_count=len(p0),
        p1_count=len(p1),
        p2_count=len(p2),
        ok=ok,
        findings=findings_data,
    )


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Lanwatch Diagnostic 主动版 v1.0 - 自动问路由器诊断",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
凭证通过环境变量提供（不进命令行/日志）：
  export ROUTER_ADMIN_USER=admin
  export ROUTER_ADMIN_PASS=your-password

示例:
  python3 active_diag.py --router 192.168.0.254 --company "客户B有限公司"
        """,
    )
    parser.add_argument("--router", default=None, help="路由器 LAN IP（如 192.168.0.254），不填则自动检测本机默认网关")
    parser.add_argument("--user", default=os.environ.get("ROUTER_ADMIN_USER", "admin"), help="管理账号")
    parser.add_argument("--company", default="", help="公司标识（报告中 hash 处理）")
    parser.add_argument("--output-dir", default="~/lanwatch_agent/diagnostic/local_runs/", help="报告输出目录")
    parser.add_argument("--timeout", type=int, default=10, help="HTTP 超时秒数")
    parser.add_argument("--debug", action="store_true", help="调试模式：打印 URL 发现和抓取过程")
    parser.add_argument("--visible", action="store_true", help="显示浏览器窗口（默认无头，需要时 --visible）")
    parser.add_argument("--method", choices=["auto", "snmp", "ssh", "web"], default="auto",
                        help="数据获取方式：auto=自动试三种 / snmp=只 SNMP / ssh=只 SSH / web=只浏览器")
    parser.add_argument("--snmp-community", default=os.environ.get("SNMP_COMMUNITY", "public"), help="SNMP community 字符串")
    args = parser.parse_args()

    password = os.environ.get("ROUTER_ADMIN_PASS")
    user_from_env = os.environ.get("ROUTER_ADMIN_USER")

    # 交互式输入用户名（仅在环境变量没设时）
    if not user_from_env:
        try:
            user_input = input(f"👤 用户名 [{args.user}]: ").strip()
            if user_input:
                args.user = user_input
        except KeyboardInterrupt:
            sys.exit("\n❌ 用户取消")

    # 交互式输入密码（环境变量未设时，隐藏输入）
    if not password:
        import getpass
        try:
            password = getpass.getpass("🔑 路由器密码（输入隐藏）：")
        except KeyboardInterrupt:
            sys.exit("\n❌ 用户取消")
        if not password:
            sys.exit("❌ ERROR: 密码不能为空\n\n可设环境变量：export ROUTER_ADMIN_PASS=xxx")

    # 自动检测路由器地址（不填 --router 时）
    if not args.router:
        detected_gateway = get_default_gateway()
        if detected_gateway:
            args.router = detected_gateway
            print(f"🔍 未指定 --router，自动检测到本机默认网关: {detected_gateway}")
        else:
            sys.exit("❌ ERROR: 未指定 --router，且无法自动检测默认网关\n\n请手动指定：python3 active_diag.py --router 192.168.0.254 ...")

    # Banner
    click_echo = lambda *a, **k: print(*a, **k)  # noqa
    print("=" * 70)
    print("🌐 Lanwatch Active Diagnostic v1.0")
    print("=" * 70)
    print(f"  路由器: {args.router}")
    print(f"  公司:   {args.company or '(未填)'}（报告中仅显示 hash）")
    print(f"  输出:   {os.path.expanduser(args.output_dir)}")
    print()

    # Login
    print(f"🔐 登录路由器 {args.router}...")
    scraper = RouterScraper(args.router, args.user, password, timeout=args.timeout)
    # 是否可见模式浏览器
    scraper.visible = args.visible
    if not scraper.login():
        sys.exit(f"❌ ERROR: 登录失败\n\n请检查：\n  1) --router 是否可达\n  2) --user / ROUTER_ADMIN_PASS 是否正确\n  3) 路由器是否允许 HTTP（非 HTTPS）登录")
    print(f"   ✅ 登录成功（CSRF token: {scraper.csrf_token[:8] if scraper.csrf_token else 'N/A'}...）")

    # 抓数据
    debug = args.debug
    method = args.method
    print(f"\n📡 抓 ARP 表（方法: {method}）...")
    arp = scraper.get_arp_table(debug=debug, snmp_community=args.snmp_community, method=method)
    print(f"   {len(arp)} 条")
    if not arp:
        print("   ⚠️  ARP 表为空（详见上方每层尝试的诊断）")

    print(f"📋 抓 DHCP 客户端列表...")
    dhcp = scraper.get_dhcp_clients(debug=debug)
    print(f"   {len(dhcp)} 条")
    if not dhcp:
        print("   ⚠️  DHCP 列表为空（URL 可能不对）")

    print(f"📊 抓流量统计...")
    flow = scraper.get_flow_stats(debug=debug)
    print(f"   {len(flow)} 条")
    if not flow:
        print("   ⚠️  流量统计为空（URL 可能不对）")

    # 分析
    print(f"\n🔍 分析...")
    analyzer = NetworkAnalyzer()
    findings = analyzer.analyze(arp, dhcp, flow)

    # 计算差集
    dhcp_ips = {c.ip for c in dhcp}
    static_count = sum(1 for e in arp if e.ip not in dhcp_ips)

    # 输出汇总
    p0 = sum(1 for f in findings if f.severity == "P0")
    p1 = sum(1 for f in findings if f.severity == "P1")
    p2 = sum(1 for f in findings if f.severity == "P2")

    print(f"\n{'=' * 70}")
    print(f"📋 诊断结果：{p0} 个 P0 + {p1} 个 P1 + {p2} 个 P2")
    print(f"{'=' * 70}\n")

    if not findings:
        print("  ✅ 未检测到异常（路由器配置健康）\n")
    else:
        for f in findings:
            icon = {"P0": "🔴", "P1": "🟡", "P2": "🟠"}[f.severity]
            print(f"  {icon} [{f.severity}] {f.title}")
            for line in f.detail.split("\n"):
                if line.strip():
                    print(f"        {line}")
            print()

    # 渲染 HTML
    print("📄 渲染 HTML 报告...")
    html = render_report(findings, args.company, args.router, len(arp), len(dhcp), len(flow), static_count)

    output_dir = os.path.expanduser(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    company_slug = hashlib.md5(args.company.encode()).hexdigest()[:6] if args.company else "anon"
    filename = f"{timestamp}.active.{company_slug}.html"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"   ✅ 报告已保存：{filepath}")
    print(f"\n🎯 用浏览器打开查看")

    if p0:
        print(f"\n🚨 检测到 {p0} 个 P0 紧急问题——建议立即处理")
    elif p1:
        print(f"\n⚠️  检测到 {p1} 个 P1 问题——建议尽快处理")
    else:
        print(f"\n✅ 未发现紧急问题")


if __name__ == "__main__":
    main()