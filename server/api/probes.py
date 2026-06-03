"""
主动探测 API：供 Web UI 或管理端主动触发探测任务。
这些接口不需要 Bearer token（由管理员操作）。
"""
import logging
from fastapi import APIRouter, Query
from typing import Optional, List

logger = logging.getLogger("probes")
from modules.ping import ping_host
from modules.traceroute import traceroute
from modules.portscan import scan_common_ports, scan_ports
from modules.dns_test import test_dns
from modules.http_check import check_url

router = APIRouter()


@router.get("/probe/ping")
async def api_ping(host: str = Query(...), count: int = Query(4)):
    """主动 ping 探测"""
    return ping_host(host, count=count)


@router.get("/probe/traceroute")
async def api_traceroute(target: str = Query(...), max_hops: int = Query(30)):
    """主动 traceroute 探测"""
    hops = traceroute(target, max_hops=max_hops)
    return {"target": target, "hops": hops, "hop_count": len(hops)}


@router.get("/probe/portscan")
async def api_portscan(host: str = Query(...), ports: Optional[str] = Query(None)):
    """
    端口扫描。
    ports 参数：逗号分隔的端口号，如 "80,443,22,3389"
    不传则扫描常用端口
    """
    port_list = None
    if ports:
        try:
            port_list = [int(p.strip()) for p in ports.split(",")]
        except ValueError:
            return {"error": "ports 参数格式错误，应为逗号分隔的数字"}
    results = scan_common_ports(host) if port_list is None else scan_ports(host, port_list)
    return {"host": host, "results": results}


@router.get("/probe/dns")
async def api_dns(domain: str = Query("www.baidu.com"), dns_server: Optional[str] = Query(None)):
    """DNS 解析测试"""
    if dns_server:
        from modules.dns_test import resolve_custom
        return resolve_custom(domain, dns_server)
    return test_dns(domain)


@router.get("/probe/http")
async def api_http(url: str = Query(...), timeout: float = Query(5.0)):
    """HTTP 健康检查"""
    return check_url(url, timeout=timeout)


@router.get("/probe/batch")
async def api_batch_probe(
    host: str = Query(...),
    types: str = Query("ping,portscan")  # 逗号分隔：ping,traceroute,portscan,dns
):
    """
    批量探测：同时执行多种探测
    types: ping,traceroute,portscan,dns,http
    """
    from modules.http_check import check_url as http_check
    result = {}
    for t in types.split(","):
        t = t.strip()
        if t == "ping":
            result["ping"] = ping_host(host)
        elif t == "traceroute":
            hops = traceroute(host)
            result["traceroute"] = {"target": host, "hops": hops}
        elif t == "portscan":
            result["portscan"] = {"host": host, "results": scan_common_ports(host)}
        elif t == "dns":
            result["dns"] = test_dns(host)
        elif t == "http":
            result["http"] = http_check(f"http://{host}")
    return result
