"""拓扑管理 API：触发发现、查询拓扑、节点/链路管理"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime, timedelta
from core.database import get_db
from core.auth import verify_admin_password
from modules.topology import topology_manager, TopologyDiscoverer

router = APIRouter()


class TopologyDiscoverRequest(BaseModel):
    agent_id: str
    seed_ips: List[str]
    community: str = "public"
    max_hops: int = 3
    max_devices: int = 50


@router.post("/topology/discover")
async def discover_topology(
    payload: TopologyDiscoverRequest,
    password: Optional[str] = Query(None),
):
    """触发拓扑发现"""
    if payload.max_hops > 5:
        raise HTTPException(status_code=400, detail="max_hops 不能超过 5")

    result = topology_manager.discover_and_save(
        agent_id=payload.agent_id,
        seed_ips=payload.seed_ips,
        community=payload.community,
    )
    return {
        "success": True,
        "discovered_count": result["discovered_count"],
        "link_count": result["link_count"],
        "message": f"发现 {result['discovered_count']} 个节点, {result['link_count']} 条链路",
    }


@router.get("/topology")
async def get_topology(agent_id: Optional[str] = Query(None)):
    """获取拓扑数据"""
    return topology_manager.get_topology(agent_id)


@router.get("/topology/nodes")
async def get_topology_nodes(
    agent_id: Optional[str] = Query(None),
    device_type: Optional[str] = Query(None),
):
    """获取拓扑节点列表，支持按类型筛选"""
    with get_db() as conn:
        cursor = conn.cursor()
        sql = "SELECT * FROM topology_nodes WHERE 1=1"
        params: list = []

        if agent_id:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        if device_type:
            sql += " AND device_type = ?"
            params.append(device_type)

        sql += " ORDER BY last_seen DESC"
        cursor.execute(sql, params)
        rows = cursor.fetchall()

        # 过滤非局域网 IP（组播、链路本地、回环、Docker 网桥）
        def _is_lan_ip(ip: str) -> bool:
            parts = ip.split(".")
            if len(parts) != 4:
                return False
            try:
                first = int(parts[0])
            except ValueError:
                return False
            if 224 <= first <= 239:  # 组播
                return False
            if first == 169 and int(parts[1]) == 254:  # 链路本地
                return False
            if first == 127:  # 回环
                return False
            if first == 172 and int(parts[1]) == 17:  # Docker 网桥
                return False
            return True

        nodes = [dict(r) for r in rows if _is_lan_ip(r["ip"])]
        return {"count": len(nodes), "nodes": nodes}


@router.get("/topology/links")
async def get_topology_links():
    """获取拓扑链路列表"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM topology_links ORDER BY last_confirmed DESC")
        rows = cursor.fetchall()
        return {"count": len(rows), "links": [dict(row) for row in rows]}


@router.get("/topology/node/{ip}")
async def get_node_detail(ip: str):
    """获取指定节点的详细信息（含告警、链路）"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM topology_nodes WHERE ip = ?", (ip,))
        node = cursor.fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="节点不存在")

        cursor.execute(
            """SELECT * FROM alert_log
               WHERE agent_id = ? OR agent_id LIKE ?
               ORDER BY created_at DESC LIMIT 10""",
            (ip, f"%{ip}%"),
        )
        alerts = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            """SELECT * FROM topology_links
               WHERE node_a_ip = ? OR node_b_ip = ?""",
            (ip, ip),
        )
        links = [dict(r) for r in cursor.fetchall()]

        return {"node": dict(node), "alerts": alerts, "links": links}


@router.delete("/topology/node/{ip}")
async def delete_node(ip: str, password: str = Query(...)):
    """删除拓扑节点"""
    verify_admin_password(password)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM topology_nodes WHERE ip = ?", (ip,))
        cursor.execute(
            "DELETE FROM topology_links WHERE node_a_ip = ? OR node_b_ip = ?",
            (ip, ip),
        )
        return {"success": True, "message": f"节点 {ip} 已删除"}


@router.get("/topology/stats")
async def get_topology_stats():
    """拓扑统计：节点/链路数、在线/离线、类型分布"""
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT device_type, COUNT(*) as cnt FROM topology_nodes GROUP BY device_type"
        )
        by_type = [
            {"type": r["device_type"], "count": r["cnt"]}
            for r in cursor.fetchall()
        ]

        cursor.execute("SELECT COUNT(*) as cnt FROM topology_links")
        link_count = cursor.fetchone()["cnt"]

        cutoff = (datetime.now() - timedelta(minutes=5)).isoformat()
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM topology_nodes WHERE last_seen >= ?",
            (cutoff,),
        )
        online_count = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) as cnt FROM topology_nodes")
        total_count = cursor.fetchone()["cnt"]

        return {
            "total_nodes": total_count,
            "online_nodes": online_count,
            "offline_nodes": total_count - online_count,
            "total_links": link_count,
            "by_type": by_type,
        }
