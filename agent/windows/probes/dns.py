"""DNS 解析测试模块"""
import dns.resolver, socket, time
from typing import Dict

DNS_SERVERS = {
    "114.114.114.114": "114DNS",
    "8.8.8.8": "Google",
    "223.5.5.5": "AliDNS",
    "119.29.29.29": "Tencent"
}


def test_dns(domain: str = "www.baidu.com") -> Dict:
    resolver = dns.resolver.Resolver()
    results = {}
    for server, name in DNS_SERVERS.items():
        resolver.nameservers = [server]
        start = time.time()
        try:
            answers = resolver.resolve(domain)
            rtt = (time.time() - start) * 1000
            results[name] = {"server": server, "ip": str(answers[0]), "rtt_ms": round(rtt, 2), "success": True}
        except dns.exception.Timeout:
            results[name] = {"server": server, "error": "超时", "success": False}
        except Exception as e:
            results[name] = {"server": server, "error": str(e), "success": False}
    return {"domain": domain, "results": results}
