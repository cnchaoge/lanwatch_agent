"""
本地诊断引擎：
- 收集本地网络状态
- 生成诊断报告供上报
"""
import subprocess, platform, socket, re, time
from typing import Dict, List


class DiagnosisEngine:
    def __init__(self):
        self.results = []

    def run_all(self) -> Dict:
        """执行所有诊断项目"""
        self.results = []
        self._check_local_network()
        self._check_gateway()
        self._check_dns()
        self._check_internet()
        return self.generate_report()

    def _check_local_network(self):
        """检查本机网络配置"""
        info = {
            "check": "local_network",
            "hostname": socket.gethostname(),
            "ip": self._get_local_ip(),
            "gateway": self._get_gateway(),
            "dns": self._get_dns(),
            "status": "ok"
        }
        self.results.append(info)

    def _check_gateway(self):
        """检查网关连通性"""
        gw = self._get_gateway()
        if not gw:
            self.results.append({"check": "gateway", "status": "unknown", "error": "无法获取网关"})
            return
        ok, rtt = self._ping(gw)
        self.results.append({
            "check": "gateway",
            "target": gw,
            "status": "ok" if ok else "unreachable",
            "rtt_ms": rtt
        })

    def _check_dns(self):
        """检查 DNS 解析"""
        try:
            dns_servers = ["114.114.114.114", "8.8.8.8"]
            for dns_ip in dns_servers:
                start = time.time()
                try:
                    socket.gethostbyname("www.baidu.com")
                    rtt = (time.time() - start) * 1000
                    self.results.append({"check": "dns", "server": dns_ip, "status": "ok", "rtt_ms": rtt})
                    return
                except Exception:
                    pass
            self.results.append({"check": "dns", "status": "failed", "error": "所有 DNS 均失败"})
        except Exception as e:
            self.results.append({"check": "dns", "status": "error", "error": str(e)})

    def _check_internet(self):
        """检查互联网连通性（ping 8.8.8.8）"""
        ok, rtt = self._ping("8.8.8.8")
        self.results.append({
            "check": "internet",
            "target": "8.8.8.8",
            "status": "ok" if ok else "unreachable",
            "rtt_ms": rtt
        })

    def _ping(self, host: str) -> tuple:
        """执行一次 ping，返回 (成功, 延迟ms)"""
        param = "-n" if platform.system().lower() == "windows" else "-c"
        try:
            output = subprocess.check_output(["ping", param, "1", "-w", "3000", host],
                                            stderr=subprocess.DEVNULL, timeout=5)
            text = output.decode(errors="ignore")
            m = re.search(r"time[=<]\s*(\d+\.?\d*)\s*ms", text, re.IGNORECASE)
            if m:
                return True, float(m.group(1))
            return True, None
        except Exception:
            return False, None

    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "unknown"

    def _get_gateway(self) -> str:
        try:
            if platform.system().lower() == "windows":
                output = subprocess.check_output("route print 0.0.0.0", stderr=subprocess.DEVNULL)
                for line in output.decode().split("\n"):
                    if "0.0.0.0" in line and not line.strip().startswith("0.0.0.0"):
                        parts = line.split()
                        if len(parts) >= 3:
                            return parts[2]
            else:
                output = subprocess.check_output("ip route | grep default", stderr=subprocess.DEVNULL)
                parts = output.decode().split()
                if "via" in parts:
                    return parts[parts.index("via") + 1]
        except Exception:
            pass
        return ""

    def _get_dns(self) -> str:
        try:
            if platform.system().lower() == "windows":
                output = subprocess.check_output("ipconfig", stderr=subprocess.DEVNULL)
                for line in output.decode().split("\n"):
                    if "DNS" in line.upper() and "IPv4" not in line:
                        parts = line.split(":")
                        if len(parts) >= 2:
                            return parts[1].strip()
            else:
                with open("/etc/resolv.conf") as f:
                    for line in f:
                        if line.startswith("nameserver"):
                            return line.split()[1]
        except Exception:
            pass
        return ""

    def generate_report(self) -> Dict:
        """生成诊断报告"""
        return {
            "triggered_by": "periodic",
            "agent_diag_time": self._get_timestamp(),
            "results": self.results,
            "summary": self._generate_summary()
        }

    def _generate_summary(self) -> str:
        checks = {r["check"]: r.get("status", "unknown") for r in self.results}
        if checks.get("gateway") == "unreachable":
            return "网关不可达"
        if checks.get("internet") == "unreachable":
            return "互联网不可达"
        if checks.get("dns") == "failed":
            return "DNS 解析失败"
        return "网络正常"

    def _get_timestamp(self) -> str:
        from datetime import datetime
        return datetime.now().isoformat()
