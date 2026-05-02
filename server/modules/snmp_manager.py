"""SNMP 设备管理：注册/删除设备、自动配置探测任务、定时采集指标"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from core.database import get_db
from core.config import config
from modules.snmp import snmp_get, snmp_bulkwalk
from modules.scheduler import scheduler

logger = logging.getLogger("snmp_manager")

# 常用 OID 列表（标量，snmp_get）
COMMON_OIDS: Dict[str, str] = {
    "1.3.6.1.2.1.1.1.0": "sysDescr",
    "1.3.6.1.2.1.1.3.0": "sysUpTime",
    "1.3.6.1.2.1.1.5.0": "sysName",
    "1.3.6.1.2.1.1.6.0": "sysLocation",
    "1.3.6.1.2.1.1.4.0": "sysContact",
    "1.3.6.1.2.1.2.1.0": "ifNumber",
}

IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"

CISCO_CPU = "1.3.6.1.4.1.9.2.1.57.0"
CISCO_MEMORY = "1.3.6.1.4.1.9.2.1.8.0"
HR_CPU = "1.3.6.1.2.1.25.3.3.1.2"


class SNMPManager:
    """SNMP 设备管理器单例"""

    def register_device(
        self,
        agent_id: str,
        ip: str,
        port: int = 161,
        community: str = "public",
        snmp_version: str = "2c",
        description: str = "",
        snmpv3_username: str = "",
        snmpv3_auth_protocol: str = "MD5",
        snmpv3_auth_key: str = "",
        snmpv3_priv_protocol: str = "DES",
        snmpv3_priv_key: str = "",
    ) -> Dict[str, Any]:
        """注册 SNMP 设备，自动创建 ping + snmp 采集任务"""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO snmp_devices (agent_id, ip, port, community, snmp_version, description,
                   snmpv3_username, snmpv3_auth_protocol, snmpv3_auth_key,
                   snmpv3_priv_protocol, snmpv3_priv_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id, ip) DO UPDATE SET
                       port=excluded.port,
                       community=excluded.community,
                       snmp_version=excluded.snmp_version,
                       description=excluded.description,
                       snmpv3_username=excluded.snmpv3_username,
                       snmpv3_auth_protocol=excluded.snmpv3_auth_protocol,
                       snmpv3_auth_key=excluded.snmpv3_auth_key,
                       snmpv3_priv_protocol=excluded.snmpv3_priv_protocol,
                       snmpv3_priv_key=excluded.snmpv3_priv_key""",
                (agent_id, ip, port, community, snmp_version, description,
                 snmpv3_username, snmpv3_auth_protocol, snmpv3_auth_key,
                 snmpv3_priv_protocol, snmpv3_priv_key),
            )
            cursor.execute("SELECT interval FROM agents WHERE agent_id=?", (agent_id,))
            row = cursor.fetchone()
            interval = row["interval"] if row else config.AGENT_DEFAULT_INTERVAL

        # 自动注册 ping 探测（健康检查）
        scheduler.add_probe_job(
            agent_id=agent_id,
            probe_type="ping",
            target=ip,
            interval_seconds=interval,
        )

        # 自动注册 snmp 采集任务（比 ping 长，减少网络压力）
        scheduler.add_probe_job(
            agent_id=agent_id,
            probe_type="snmp",
            target=ip,
            interval_seconds=max(interval * 5, 300),
        )

        logger.info(f"注册 SNMP 设备: {agent_id} -> {ip}:{port} v{snmp_version}")
        return {
            "success": True,
            "agent_id": agent_id,
            "ip": ip,
            "port": port,
            "message": "设备注册成功，探测任务已自动创建",
        }

    def unregister_device(self, agent_id: str, ip: str) -> Dict[str, Any]:
        """取消注册 SNMP 设备，移除探测任务"""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM snmp_devices WHERE agent_id=? AND ip=?", (agent_id, ip)
            )
            if cursor.rowcount > 0:
                scheduler.remove_probe_job(agent_id, "ping", ip)
                scheduler.remove_probe_job(agent_id, "snmp", ip)
                logger.info(f"取消注册 SNMP 设备: {agent_id} -> {ip}")
                return {"success": True, "message": f"设备 {ip} 已移除"}
            return {"success": False, "message": "设备不存在"}

    def list_devices(self, agent_id: str) -> List[Dict]:
        """列出指定 Agent 下的所有 SNMP 设备"""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM snmp_devices WHERE agent_id=? ORDER BY created_at DESC",
                (agent_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def collect_snmp_metrics(self, agent_id: str, ip: str) -> Dict[str, Any]:
        """采集指定设备的 SNMP 指标，支持 v2c 和 v3"""
        with get_db() as conn:
            cursor = conn.cursor()
            if agent_id:
                cursor.execute(
                    "SELECT port, community, snmp_version, snmpv3_username, snmpv3_auth_protocol, snmpv3_auth_key, snmpv3_priv_protocol, snmpv3_priv_key FROM snmp_devices WHERE agent_id=? AND ip=?",
                    (agent_id, ip),
                )
            else:
                cursor.execute(
                    "SELECT port, community, snmp_version, snmpv3_username, snmpv3_auth_protocol, snmpv3_auth_key, snmpv3_priv_protocol, snmpv3_priv_key FROM snmp_devices WHERE ip=? LIMIT 1",
                    (ip,),
                )
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "设备未注册"}

            dev = dict(row)
            port = dev["port"]
            community = dev["community"]
            snmp_version = dev.get("snmp_version", "2c")

        results: Dict[str, str] = {}

        for oid, name in COMMON_OIDS.items():
            ok, val = snmp_get(ip, oid, community, port=port,
                               snmp_version=snmp_version,
                               v3_username=dev.get("snmpv3_username", ""),
                               v3_auth_protocol=dev.get("snmpv3_auth_protocol", "MD5"),
                               v3_auth_key=dev.get("snmpv3_auth_key", ""),
                               v3_priv_protocol=dev.get("snmpv3_priv_protocol", "DES"),
                               v3_priv_key=dev.get("snmpv3_priv_key", ""))
            if ok and not val.startswith("No Such"):
                results[name] = str(val)

        if_rows = snmp_bulkwalk(ip, IF_OPER_STATUS, community, port=port,
                                snmp_version=snmp_version,
                                v3_username=dev.get("snmpv3_username", ""),
                                v3_auth_protocol=dev.get("snmpv3_auth_protocol", "MD5"),
                                v3_auth_key=dev.get("snmpv3_auth_key", ""),
                                v3_priv_protocol=dev.get("snmpv3_priv_protocol", "DES"),
                                v3_priv_key=dev.get("snmpv3_priv_key", ""),
                                max_rows=50)
        if_up = 0
        if_down = 0
        for oid_str, val_str in if_rows:
            # 仅处理 IF_OPER_STATUS 子树内的 OID，跳过后续列
            if not oid_str.startswith(IF_OPER_STATUS):
                continue
            try:
                idx = oid_str.rsplit(".", 1)[-1]
                results[f"ifStatus_{idx}"] = str(val_str)
                if val_str == "1":
                    if_up += 1
                elif val_str == "2":
                    if_down += 1
            except Exception:
                pass
        results["ifUpCount"] = str(if_up)
        results["ifDownCount"] = str(if_down)

        # 采集 CPU（hrProcessorLoad 是表，walk 取平均）
        cpu_rows = snmp_bulkwalk(ip, HR_CPU, community, port=port,
                                 snmp_version=snmp_version,
                                 v3_username=dev.get("snmpv3_username", ""),
                                 v3_auth_protocol=dev.get("snmpv3_auth_protocol", "MD5"),
                                 v3_auth_key=dev.get("snmpv3_auth_key", ""),
                                 v3_priv_protocol=dev.get("snmpv3_priv_protocol", "DES"),
                                 v3_priv_key=dev.get("snmpv3_priv_key", ""),
                                 max_rows=16)
        cpu_vals = []
        for oid_str, val_str in cpu_rows:
            if not oid_str.startswith(HR_CPU):
                continue
            try:
                cpu_vals.append(int(val_str))
            except (ValueError, TypeError):
                pass
        if cpu_vals:
            results["hrProcessorLoad"] = str(round(sum(cpu_vals) / len(cpu_vals)))
        # 尝试 Cisco CPU（单 OID）
        ok, val = snmp_get(ip, CISCO_CPU, community, port=port,
                           snmp_version=snmp_version,
                           v3_username=dev.get("snmpv3_username", ""),
                           v3_auth_protocol=dev.get("snmpv3_auth_protocol", "MD5"),
                           v3_auth_key=dev.get("snmpv3_auth_key", ""),
                           v3_priv_protocol=dev.get("snmpv3_priv_protocol", "DES"),
                           v3_priv_key=dev.get("snmpv3_priv_key", ""))
        if ok and not val.startswith("No Such"):
            results["ciscoCpu"] = str(val)
        # 尝试 Cisco 内存
        ok, val = snmp_get(ip, CISCO_MEMORY, community, port=port,
                           snmp_version=snmp_version,
                           v3_username=dev.get("snmpv3_username", ""),
                           v3_auth_protocol=dev.get("snmpv3_auth_protocol", "MD5"),
                           v3_auth_key=dev.get("snmpv3_auth_key", ""),
                           v3_priv_protocol=dev.get("snmpv3_priv_protocol", "DES"),
                           v3_priv_key=dev.get("snmpv3_priv_key", ""))
        if ok and not val.startswith("No Such"):
            results["ciscoMemory"] = str(val)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            cursor = conn.cursor()
            for oid, value in results.items():
                raw_hex = value.encode().hex()[:64] if isinstance(value, str) else ""
                cursor.execute(
                    """INSERT INTO snmp_metrics (device_ip, oid, value, raw_hex, raw_len, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (ip, oid, value, raw_hex, len(raw_hex) // 2 if raw_hex else 0, now),
                )
            status = "online" if results else "offline"
            cursor.execute(
                "UPDATE snmp_devices SET status=?, last_poll=? WHERE ip=?",
                (status, now, ip),
            )

        return {
            "success": True,
            "ip": ip,
            "metrics_count": len(results),
            "sample": dict(list(results.items())[:5]),
        }

    def collect_all_devices(self):
        """采集所有注册设备的数据（由调度器定期调用）"""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT agent_id, ip FROM snmp_devices")
            devices = cursor.fetchall()

        for device in devices:
            try:
                self.collect_snmp_metrics(device["agent_id"], device["ip"])
            except Exception as e:
                logger.error(f"采集 {device['ip']} 失败: {e}")

    def ensure_snmp_jobs(self):
        """确保所有已注册的 SNMP 设备都有对应的探测任务（启动时调用）"""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM snmp_devices")
            for row in cursor.fetchall():
                d = dict(row)
                self.register_device(
                    agent_id=d["agent_id"],
                    ip=d["ip"],
                    port=d["port"],
                    community=d["community"],
                    snmp_version=d["snmp_version"],
                    description=d.get("description", ""),
                    snmpv3_username=d.get("snmpv3_username", ""),
                    snmpv3_auth_protocol=d.get("snmpv3_auth_protocol", "MD5"),
                    snmpv3_auth_key=d.get("snmpv3_auth_key", ""),
                    snmpv3_priv_protocol=d.get("snmpv3_priv_protocol", "DES"),
                    snmpv3_priv_key=d.get("snmpv3_priv_key", ""),
                )


snmp_manager = SNMPManager()
