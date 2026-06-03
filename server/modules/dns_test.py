import dns.resolver, socket, time
import logging
logger = logging.getLogger("dns_test")
from typing import Dict, List

DNS_SERVERS = {
    "114.114.114.114": "114DNS",
    "8.8.8.8": "Google",
    "223.5.5.5": "AliDNS",
    "119.29.29.29": "Tencent"
}


def test_dns(domain: str = "www.baidu.com") -> Dict:
    """
    测试多个 DNS 服务器对同一域名的解析结果。
    返回: {
        "domain": "www.baidu.com",
        "results": {
            "114DNS": {"server": "114.114.114.114", "ip": "220.181.38.150", "rtt_ms": 28.5, "success": True},
            "Google": {"server": "8.8.8.8", "error": "timeout", "success": False},
            ...
        }
    }
    """
    resolver_obj = dns.resolver.Resolver()
    results = {}

    for server, name in DNS_SERVERS.items():
        resolver_obj.nameservers = [server]
        start = time.time()
        try:
            answers = resolver_obj.resolve(domain)
            rtt = (time.time() - start) * 1000
            results[name] = {
                "server": server, "ip": str(answers[0]), "rtt_ms": round(rtt, 2), "success": True
            }
        except dns.resolver.NXDOMAIN:
            results[name] = {"server": server, "error": "域名不存在", "success": False}
        except dns.resolver.NoAnswer:
            results[name] = {"server": server, "error": "无解析记录", "success": False}
        except dns.exception.Timeout:
            results[name] = {"server": server, "error": "超时", "success": False}
        except Exception as e:
            logger.warning("DNS 解析异常 [%s/%s]: %s", name, domain, e)
            results[name] = {"server": server, "error": str(e), "success": False}

    return {"domain": domain, "results": results}


def resolve_custom(domain: str, dns_server: str = None) -> Dict:
    """使用指定 DNS 服务器解析域名"""
    resolver_obj = dns.resolver.Resolver()
    if dns_server:
        resolver_obj.nameservers = [dns_server]
    try:
        answers = resolver_obj.resolve(domain)
        return {"domain": domain, "dns_server": dns_server or "system", "ip": str(answers[0]), "success": True}
    except Exception as e:
        return {"domain": domain, "dns_server": dns_server or "system", "error": str(e), "success": False}
