"""故障传播链 + 告警关联 API：传播链查询、根因分析、告警聚类关联"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List
from modules.propagation import propagation_analyzer
from modules.topology import topology_manager

router = APIRouter()


@router.get("/propagation/chain/{ip}")
async def get_propagation_chain(
    ip: str,
    depth: int = Query(default=3, ge=1, le=5),
):
    """获取指定设备为根因的故障传播链。展示该设备故障后可能影响哪些下游设备。"""
    chain = propagation_analyzer.build_propagation_chain(ip, depth)

    return {
        "root_ip": ip,
        "depth": depth,
        "chain": chain,
        "summary": {
            "total_affected": chain.get("total_affected", 0),
            "max_depth": chain.get("max_depth", 0),
        },
    }


@router.post("/propagation/root_cause")
async def find_root_cause(
    affected_ips: List[str] = Query(..., description="受影响设备的 IP 列表"),
):
    """给定一组受影响设备的 IP，分析最可能的根因设备。"""
    if not affected_ips:
        raise HTTPException(status_code=400, detail="affected_ips 不能为空")

    candidates = propagation_analyzer.find_root_cause(affected_ips)

    return {
        "affected_ips": affected_ips,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


@router.get("/propagation/correlate")
async def correlate_alerts(
    agent_id: Optional[str] = Query(None),
    hours: int = Query(default=24, ge=1, le=168),
):
    """告警关联分析。将时间相近的告警聚类，识别根因告警和派生告警。"""
    result = propagation_analyzer.correlate_alerts(agent_id, hours)
    return result


@router.get("/propagation/topology_impact/{ip}")
async def get_topology_impact(
    ip: str,
    depth: int = Query(default=2, ge=1, le=4),
):
    """获取指定设备故障对拓扑的影响范围。返回受影响设备类型分布。"""
    topo = topology_manager.get_topology()
    nodes = {n["ip"]: n for n in topo.get("nodes", [])}

    chain = propagation_analyzer.build_propagation_chain(ip, depth)

    def count_types(node_dict: dict, counts: dict):
        device_type = node_dict.get("device_type", "unknown")
        counts[device_type] = counts.get(device_type, 0) + 1
        for child in node_dict.get("children", []):
            count_types(child, counts)

    type_counts = {}
    count_types(chain["root"], type_counts)

    has_critical = any(t in type_counts for t in ("router", "firewall"))

    return {
        "device_ip": ip,
        "device_type": nodes.get(ip, {}).get("device_type", "unknown"),
        "hostname": nodes.get(ip, {}).get("hostname", ""),
        "analysis_depth": depth,
        "total_affected": chain.get("total_affected", 0),
        "affected_types": type_counts,
        "has_critical_affected": has_critical,
        "propagation_tree": chain,
    }
