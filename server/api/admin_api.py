"""管理后台 API：企业列表、SNMP 管理等"""
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from pydantic import BaseModel
from core.database import get_db
from core.config import config

router = APIRouter()


def _verify_admin(payload: dict = None, password: str = None):
    pw = password or (payload or {}).get("password", "")
    if pw != config.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="密码错误")


@router.post("/admin/login")
async def admin_login(payload: dict):
    password = payload.get("password", "")
    if password == config.ADMIN_PASSWORD:
        return {"success": True, "message": "登录成功"}
    raise HTTPException(status_code=401, detail="密码错误")


# ── 企业（= agents 表）管理 ─────────────────────────────────────────


@router.get("/admin/users")
async def admin_get_users():
    """返回所有企业（agent），含拓扑节点作为设备列表"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT agent_id, name, token, ip, os_type, last_seen FROM agents ORDER BY created_at DESC"
        )
        rows = cursor.fetchall()
        result = []
        for r in rows:
            aid = r["agent_id"]
            # 把拓扑节点作为该企业下的设备
            cursor.execute(
                "SELECT id, ip, hostname, device_type, last_seen FROM topology_nodes WHERE agent_id = ? ORDER BY last_seen DESC",
                (aid,),
            )
            devices = []
            for d in cursor.fetchall():
                d = dict(d)
                devices.append({
                    "id": str(d["id"]),
                    "agent_id": aid,
                    "name": d.get("hostname") or d.get("ip", ""),
                    "ip": d.get("ip", ""),
                    "device_type": d.get("device_type", ""),
                    "last_seen": d.get("last_seen"),
                })
            # 查询该企业关联的 ping 监控状态（先按 agent_id 匹配，再按 IP 匹配）
            ping_status = None
            cursor.execute(
                """SELECT sj.enabled, pr.status as last_status, pr.rtt_ms as last_rtt,
                          pr.created_at as last_check
                   FROM scheduler_jobs sj
                   LEFT JOIN (
                       SELECT target, status, rtt_ms, created_at,
                              ROW_NUMBER() OVER (PARTITION BY target ORDER BY created_at DESC) rn
                       FROM probe_results WHERE probe_type='ping'
                   ) pr ON sj.target = pr.target AND pr.rn = 1
                   WHERE sj.probe_type='ping'
                     AND (sj.agent_id=? OR (sj.agent_id='admin' AND sj.target=?))
                   ORDER BY CASE WHEN sj.agent_id=? THEN 0 ELSE 1 END
                   LIMIT 1""",
                (aid, r["ip"], aid),
            )
            ping_row = cursor.fetchone()
            if ping_row:
                pr = dict(ping_row)
                ping_status = {
                    "enabled": bool(pr.get("enabled", 1)),
                    "status": "online" if pr.get("last_status") == "ok" else "offline",
                    "rtt_ms": pr.get("last_rtt"),
                }
                if pr.get("last_check"):
                    try:
                        ping_status["last_seen"] = datetime.fromisoformat(pr["last_check"] + "+00:00").timestamp()
                    except Exception:
                        pass

            result.append({
                "id": aid,
                "name": r["name"] or "",
                "phone": "",
                "token": r["token"],
                "agents": devices,
                "ip": r["ip"] or "",
                "os_type": r["os_type"] or "",
                "last_seen": r["last_seen"],
                "ping": ping_status,
            })
        return result


@router.post("/admin/users")
async def admin_create_user(payload: dict):
    """手动创建企业，可选 IP 地址自动创建连通性监控"""
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="企业名称不能为空")
    phone = (payload.get("phone") or "").strip()
    ip = (payload.get("ip") or "").strip()
    agent_id = secrets.token_hex(16)
    token = secrets.token_hex(32)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO agents (agent_id, name, token, ip) VALUES (?, ?, ?, ?)",
            (agent_id, name, token, ip),
        )

    # 如果提供了 IP，自动创建连通性监控
    if ip:
        from modules.scheduler import scheduler
        job_id = f"{agent_id}:ping:{ip}"
        scheduler.add_job(job_id, agent_id, "ping", ip,
                          interval_seconds=60,
                          name=name)

    return {"success": True, "agent_id": agent_id, "token": token}


@router.patch("/admin/users/{user_id}")
async def admin_update_user(user_id: str, payload: dict):
    name = (payload.get("name") or "").strip()
    ip = (payload.get("ip") or "").strip()
    with get_db() as conn:
        cursor = conn.cursor()
        if name:
            cursor.execute("UPDATE agents SET name = ? WHERE agent_id = ?", (name, user_id))
        if ip:
            cursor.execute("UPDATE agents SET ip = ? WHERE agent_id = ?", (ip, user_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="企业不存在")

    # 如果更新了 IP，同步更新 ping 监控
    if ip:
        from modules.scheduler import scheduler
        job_id = f"{user_id}:ping:{ip}"
        scheduler.add_job(job_id, user_id, "ping", ip,
                          interval_seconds=60,
                          name=name or payload.get("name", ""))
    return {"success": True}


@router.post("/admin/users/{user_id}/reset-token")
async def admin_reset_token(user_id: str):
    token = secrets.token_hex(32)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE agents SET token = ? WHERE agent_id = ?", (token, user_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="企业不存在")
    return {"token": token}


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM topology_nodes WHERE agent_id = ?", (user_id,))
        # topology_links 表无 agent_id 字段，跳过
        cursor.execute("DELETE FROM probe_results WHERE agent_id = ?", (user_id,))
        cursor.execute("DELETE FROM alert_log WHERE agent_id = ?", (user_id,))
        cursor.execute("DELETE FROM agents WHERE agent_id = ?", (user_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="企业不存在")
    return {"success": True}


# ── 设备（= topology_nodes）管理 ────────────────────────────────────


@router.patch("/admin/agents/{agent_id}")
async def admin_update_agent(agent_id: str, payload: dict):
    """更新拓扑节点信息"""
    name = (payload.get("name") or "").strip()
    with get_db() as conn:
        cursor = conn.cursor()
        if name:
            cursor.execute(
                "UPDATE topology_nodes SET hostname = ? WHERE id = ?",
                (name, agent_id),
            )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="设备不存在")
    return {"success": True}


@router.delete("/admin/agents/{agent_id}")
async def admin_delete_agent(agent_id: str):
    """删除拓扑节点"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM topology_nodes WHERE id = ?", (agent_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="设备不存在")
    return {"success": True}


# ── SNMP 设备管理 ────────────────────────────────────────────────────


@router.get("/admin/snmp")
async def admin_get_snmp():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, agent_id, ip, community, device_name, device_type, snmp_version, status, last_poll, snmpv3_username, snmpv3_auth_protocol, snmpv3_priv_protocol FROM snmp_devices ORDER BY device_name"
        )
        rows = cursor.fetchall()
        return [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "ip": r["ip"],
                "community": r["community"],
                "device_name": r["device_name"] or "",
                "device_type": r["device_type"] or "unknown",
                "snmp_version": r["snmp_version"] or "2c",
                "status": r["status"] or "unknown",
                "last_poll": r["last_poll"],
                "snmpv3_username": r["snmpv3_username"] or "",
                "snmpv3_auth_protocol": r["snmpv3_auth_protocol"] or "MD5",
                "snmpv3_priv_protocol": r["snmpv3_priv_protocol"] or "DES",
            }
            for r in rows
        ]


@router.post("/admin/snmp")
async def admin_create_snmp(payload: dict):
    ip = (payload.get("ip") or "").strip()
    if not ip:
        raise HTTPException(status_code=400, detail="IP 地址不能为空")
    agent_id = payload.get("agent_id", "admin")
    snmp_version = payload.get("snmp_version", "2c")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO snmp_devices (agent_id, ip, community, device_name, device_type, snmp_version,
               snmpv3_username, snmpv3_auth_protocol, snmpv3_auth_key,
               snmpv3_priv_protocol, snmpv3_priv_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, ip, payload.get("community", "public"),
             payload.get("device_name", ""), payload.get("device_type", "router"),
             snmp_version,
             payload.get("snmpv3_username", ""),
             payload.get("snmpv3_auth_protocol", "MD5"),
             payload.get("snmpv3_auth_key", ""),
             payload.get("snmpv3_priv_protocol", "DES"),
             payload.get("snmpv3_priv_key", "")),
        )
    # 创建调度任务让设备能被定时轮询
    from modules.scheduler import scheduler
    from core.config import config
    scheduler.add_probe_job(agent_id=agent_id, probe_type="ping", target=ip, interval_seconds=config.AGENT_DEFAULT_INTERVAL)
    scheduler.add_probe_job(agent_id=agent_id, probe_type="snmp", target=ip, interval_seconds=max(config.AGENT_DEFAULT_INTERVAL * 5, 300))
    return {"success": True}


@router.patch("/admin/snmp/{device_id}")
async def admin_update_snmp(device_id: int, payload: dict):
    snmp_version = payload.get("snmp_version", "2c")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE snmp_devices SET ip=?, community=?, device_name=?, device_type=?,
               snmp_version=?, snmpv3_username=?, snmpv3_auth_protocol=?,
               snmpv3_auth_key=?, snmpv3_priv_protocol=?, snmpv3_priv_key=? WHERE id=?""",
            (
                payload.get("ip", ""),
                payload.get("community", "public"),
                payload.get("device_name", ""),
                payload.get("device_type", "router"),
                snmp_version,
                payload.get("snmpv3_username", ""),
                payload.get("snmpv3_auth_protocol", "MD5"),
                payload.get("snmpv3_auth_key", ""),
                payload.get("snmpv3_priv_protocol", "DES"),
                payload.get("snmpv3_priv_key", ""),
                device_id,
            ),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="SNMP 设备不存在")
    return {"success": True}


@router.delete("/admin/snmp/{device_id}")
async def admin_delete_snmp(device_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM snmp_devices WHERE id = ?", (device_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="SNMP 设备不存在")
    return {"success": True}


@router.post("/admin/snmp/{device_id}/poll")
async def admin_poll_snmp(device_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ip, agent_id FROM snmp_devices WHERE id = ?", (device_id,))
        dev = cursor.fetchone()
        if not dev:
            raise HTTPException(status_code=404, detail="SNMP 设备不存在")
    from modules.snmp_manager import snmp_manager
    result = snmp_manager.collect_snmp_metrics(dev["agent_id"], dev["ip"])
    return {"status": "ok", "message": "轮询完成", "data": result}


# ── 掉线检测（Ping 监控目标）CRUD ──────────────────────────────────────


@router.get("/admin/ping")
async def admin_get_ping_monitors():
    """获取所有 ping 监控目标及最新状态"""
    from modules.ping import ping_host
    monitors = []
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT sj.*, pr.status as last_status, pr.rtt_ms as last_rtt,
                      pr.created_at as last_check
               FROM scheduler_jobs sj
               LEFT JOIN (
                   SELECT target, status, rtt_ms, created_at,
                          ROW_NUMBER() OVER (PARTITION BY target ORDER BY created_at DESC) rn
                   FROM probe_results WHERE probe_type='ping'
               ) pr ON sj.target = pr.target AND pr.rn = 1
               WHERE sj.probe_type='ping'
               ORDER BY sj.created_at DESC"""
        )
        for row in cursor.fetchall():
            d = dict(row)
            d["id"] = d["job_id"]
            # 名称优先取 DB 保存的 name，没有则回退到 target
            d["name"] = d.get("name") or d["target"]
            d["ip"] = d["target"]
            d["rtt_ms"] = d.get("last_rtt")
            d["status"] = "online" if d.get("last_status") == "ok" else "offline"
            d["last_seen"] = None
            if d["last_check"]:
                try:
                    d["last_seen"] = datetime.fromisoformat(d["last_check"] + "+00:00").timestamp()
                except Exception:
                    pass
            d["enabled"] = bool(d.get("enabled", 1))
            d["interval_sec"] = d.get("interval_seconds", 300)
            monitors.append(d)
    return monitors


class PingMonitorCreate(BaseModel):
    name: str = ""
    ip: str
    interval_seconds: int = 60


@router.post("/admin/ping")
async def admin_create_ping_monitor(payload: PingMonitorCreate):
    """创建新的 ping 监控目标"""
    ip = payload.ip.strip()
    if not ip:
        raise HTTPException(status_code=400, detail="IP 地址不能为空")

    from modules.scheduler import scheduler
    agent_id = "admin"
    job_id = f"{agent_id}:ping:{ip}"

    scheduler.add_job(job_id, agent_id, "ping", ip,
                      interval_seconds=payload.interval_seconds or 60,
                      name=payload.name)
    return {"success": True, "id": job_id, "ip": ip, "message": "监控目标已创建"}


@router.patch("/admin/ping/{job_id}")
async def admin_update_ping_monitor(job_id: str, payload: dict):
    """更新 ping 监控目标（启用/禁用、修改间隔）"""
    enabled = payload.get("enabled")
    interval_seconds = payload.get("interval_seconds")
    name = payload.get("name")

    with get_db() as conn:
        cursor = conn.cursor()
        if name:
            cursor.execute(
                "UPDATE scheduler_jobs SET name=? WHERE job_id=?",
                (name, job_id),
            )
        if enabled is not None:
            cursor.execute(
                "UPDATE scheduler_jobs SET enabled=? WHERE job_id=?",
                (1 if enabled else 0, job_id),
            )
        if interval_seconds:
            cursor.execute(
                "UPDATE scheduler_jobs SET interval_seconds=? WHERE job_id=?",
                (interval_seconds, job_id),
            )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="监控目标不存在")

    # 重新加载调度器
    from modules.scheduler import scheduler
    scheduler.reload_jobs_from_db()
    return {"success": True}


@router.delete("/admin/ping/{job_id}")
async def admin_delete_ping_monitor(job_id: str):
    """删除 ping 监控目标"""
    from modules.scheduler import scheduler
    scheduler.remove_job(job_id)
    return {"success": True, "message": "监控目标已删除"}


@router.post("/admin/ping/{job_id}/test")
async def admin_test_ping_monitor(job_id: str):
    """立即对监控目标执行一次 ping 测试"""
    from modules.ping import ping_host
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT target FROM scheduler_jobs WHERE job_id=? AND probe_type='ping'",
            (job_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="监控目标不存在")
        target = row["target"]

    result = ping_host(target, count=4)
    return {
        "online": result.get("status") == "ok",
        "ip": target,
        "rtt_ms": result.get("avg_rtt"),
        "loss_pct": result.get("loss"),
    }


@router.get("/admin/ping/{job_id}/history")
async def admin_ping_history(job_id: str, hours: int = Query(default=24, ge=1, le=168)):
    """获取 ping 监控历史（RTT 趋势 + 可用率）"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT target FROM scheduler_jobs WHERE job_id=? AND probe_type='ping'",
            (job_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="监控目标不存在")
        target = row["target"]

        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        cursor.execute(
            """SELECT created_at, rtt_ms, status FROM probe_results
               WHERE target=? AND probe_type='ping' AND created_at >= ?
               ORDER BY created_at ASC LIMIT 500""",
            (target, cutoff),
        )
        rows = cursor.fetchall()

        rtt_history = []
        up_history = []
        up_buckets: dict = {}
        for r in rows:
            ts = r["created_at"]
            try:
                epoch = datetime.fromisoformat(ts + "+00:00").timestamp()
            except Exception:
                continue
            if r["rtt_ms"] is not None:
                rtt_history.append({"ts": epoch, "rtt_ms": r["rtt_ms"]})
            # 按天分桶计算可用率
            day_key = ts[:10]
            if day_key not in up_buckets:
                up_buckets[day_key] = {"total": 0, "ok": 0}
            up_buckets[day_key]["total"] += 1
            if r["status"] == "ok":
                up_buckets[day_key]["ok"] += 1

        for day_key, bucket in sorted(up_buckets.items()):
            up_history.append({
                "ts": day_key,
                "up_pct": round(bucket["ok"] / bucket["total"] * 100, 1) if bucket["total"] else 0,
            })

        # 最近 20 条原始记录
        cursor.execute(
            """SELECT created_at, rtt_ms, status FROM probe_results
               WHERE target=? AND probe_type='ping'
               ORDER BY created_at DESC LIMIT 20""",
            (target,),
        )
        recent_results = []
        for r in cursor.fetchall():
            ts = r["created_at"]
            try:
                epoch = datetime.fromisoformat(ts + "+00:00").timestamp()
            except Exception:
                epoch = 0
            recent_results.append({
                "ts": epoch,
                "rtt_ms": r["rtt_ms"],
                "status": r["status"],
            })
        recent_results.reverse()

        # 统计摘要
        cursor.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) as ok_count,
                      AVG(CASE WHEN rtt_ms IS NOT NULL THEN rtt_ms ELSE NULL END) as avg_rtt,
                      MIN(rtt_ms) as min_rtt,
                      MAX(rtt_ms) as max_rtt
               FROM probe_results
               WHERE target=? AND probe_type='ping' AND created_at >= ?""",
            (target, cutoff),
        )
        stats = dict(cursor.fetchone())

        return {
            "rtt_history": rtt_history,
            "up_history": up_history,
            "recent_results": recent_results,
            "stats": stats,
        }


# ── 监控目标管理（v1.3.0）──────────────────────────────────────────

@router.get("/admin/targets")
async def admin_list_targets(password: str = Query(...)):
    """列出所有监控目标（含所属企业名称）"""
    _verify_admin(password=password)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT t.id, t.agent_id, t.name, t.target, t.probe_type,
                   t.port, t.timeout, t.interval, t.enabled, t.created_at,
                   a.name as agent_name
            FROM targets t
            LEFT JOIN agents a ON t.agent_id = a.agent_id
            ORDER BY t.id DESC
        """)
        rows = cursor.fetchall()
        return [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "agent_name": r["agent_name"] or r["agent_id"],
                "name": r["name"] or "",
                "target": r["target"],
                "probe_type": r["probe_type"],
                "port": r["port"],
                "timeout": r["timeout"],
                "interval": r["interval"],
                "enabled": bool(r["enabled"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]


@router.post("/admin/targets")
async def admin_create_target(payload: dict, password: str = Query(...)):
    """新建监控目标"""
    _verify_admin(password=password)
    required = ["agent_id", "target", "probe_type"]
    for f in required:
        if not payload.get(f):
            raise HTTPException(status_code=400, detail=f"缺少必填字段: {f}")
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO targets (agent_id, name, target, probe_type, port, timeout, interval, enabled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    payload["agent_id"],
                    payload.get("name", ""),
                    payload["target"],
                    payload["probe_type"],
                    payload.get("port", 80),
                    payload.get("timeout", 5),
                    payload.get("interval", 60),
                    1 if payload.get("enabled", True) else 0,
                ),
            )
            return {"success": True, "id": cursor.lastrowid}
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                raise HTTPException(status_code=409, detail="该目标已存在")
            raise HTTPException(status_code=500, detail=str(e))


@router.put("/admin/targets/{target_id}")
async def admin_update_target(target_id: int, payload: dict, password: str = Query(...)):
    """更新监控目标"""
    _verify_admin(password=password)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM targets WHERE id = ?", (target_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="目标不存在")
        fields, values = [], []
        for col in ["name", "target", "probe_type", "port", "timeout", "interval"]:
            if col in payload:
                fields.append(f"{col} = ?")
                values.append(payload[col])
        if "enabled" in payload:
            fields.append("enabled = ?")
            values.append(1 if payload["enabled"] else 0)
        if not fields:
            raise HTTPException(status_code=400, detail="没有要更新的字段")
        values.append(target_id)
        cursor.execute(f"UPDATE targets SET {', '.join(fields)} WHERE id = ?", values)
        return {"success": True}


@router.delete("/admin/targets/{target_id}")
async def admin_delete_target(target_id: int, password: str = Query(...)):
    """删除监控目标"""
    _verify_admin(password=password)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM targets WHERE id = ?", (target_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="目标不存在")
        return {"success": True}
