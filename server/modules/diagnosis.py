"""智能诊断引擎：基于探测结果的根因分析和排查建议"""
import ast
import logging
from typing import Dict, List, Any, Optional
from enum import Enum
from datetime import datetime, timedelta
from core.database import get_db

logger = logging.getLogger("diagnosis")


class Severity(Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class DiagnosisRule:
    """诊断规则：症状模式、可能原因和排查路径"""

    def __init__(
        self,
        rule_id: str,
        symptom_type: str,
        trigger_condition: str,
        possible_causes: List[Dict],
        diagnostic_steps: List[str],
        recommended_actions: List[str],
        severity: Severity = Severity.WARNING,
    ):
        self.rule_id = rule_id
        self.symptom_type = symptom_type
        self.trigger_condition = trigger_condition
        self.possible_causes = possible_causes
        self.diagnostic_steps = diagnostic_steps
        self.recommended_actions = recommended_actions
        self.severity = severity


# ===== 内置诊断规则库 =====
DIAGNOSIS_RULES: List[DiagnosisRule] = [

    # ---- Ping 100% 丢包 ----
    DiagnosisRule(
        rule_id="ping_100_loss",
        symptom_type="ping_100_loss",
        trigger_condition="result.get('received', 4) == 0",
        possible_causes=[
            {"cause": "设备宕机", "probability": 0.60,
             "description": "目标主机已关机或崩溃"},
            {"cause": "网络链路中断", "probability": 0.25,
             "description": "中间网络设备或链路故障"},
            {"cause": "防火墙拦截", "probability": 0.10,
             "description": "目标或中间设备防火墙阻止 ICMP"},
            {"cause": "ACL 规则阻止", "probability": 0.05,
             "description": "网络 ACL 禁止 ICMP 流量"},
        ],
        diagnostic_steps=[
            "1. 确认目标 IP 是否正确",
            "2. 确认目标设备是否开机",
            "3. 从同网段其他设备 ping 该 IP",
            "4. 检查目标设备网线是否脱落",
            "5. 检查上游交换机/路由器端口状态",
            "6. 查看告警历史确认是否有设备突然离线",
            "7. 如有 SNMP 监控，查看该设备最后在线时间",
            "8. traceroute 到目标 IP 定位中断点",
        ],
        recommended_actions=[
            "通知机房运维人员现场检查",
            "检查设备是否掉电",
            "登录上游交换机检查端口状态",
        ],
        severity=Severity.CRITICAL,
    ),

    # ---- Ping 部分丢包 ----
    DiagnosisRule(
        rule_id="ping_partial_loss",
        symptom_type="ping_partial_loss",
        trigger_condition="0 < result.get('received', 4) < 4 and (result.get('loss_rate', 0) or 0) > 0.05",
        possible_causes=[
            {"cause": "链路拥塞", "probability": 0.40,
             "description": "网络带宽不足或发生拥塞"},
            {"cause": "设备负载过高", "probability": 0.25,
             "description": "中间设备 CPU/内存负载高"},
            {"cause": "无线干扰（AP场景）", "probability": 0.15,
             "description": "无线信号干扰或信道冲突"},
            {"cause": "网线质量差", "probability": 0.10,
             "description": "网线老化或质量差导致误码"},
            {"cause": "双工不匹配", "probability": 0.10,
             "description": "端口双工模式不一致导致丢包"},
        ],
        diagnostic_steps=[
            "1. 通过 traceroute 定位丢包发生在哪一跳",
            "2. 检查丢包节点的设备负载",
            "3. 检查丢包节点的端口带宽和流量",
            "4. 查看是否有突发大流量",
            "5. 确认两端端口双工模式一致",
            "6. 检查交换机端口错误计数",
            "7. 更换网线测试",
        ],
        recommended_actions=[
            "检查网络设备 CPU/内存",
            "检查端口带宽利用率",
            "排查是否有突发流量",
        ],
        severity=Severity.WARNING,
    ),

    # ---- Ping 高延迟 ----
    DiagnosisRule(
        rule_id="ping_high_latency",
        symptom_type="ping_high_latency",
        trigger_condition="(result.get('avg_rtt_ms', 0) or 0) > 200",
        possible_causes=[
            {"cause": "链路拥塞", "probability": 0.45,
             "description": "链路带宽被占满，排队延迟高"},
            {"cause": "路由绕路", "probability": 0.20,
             "description": "路由路径非最优，绕行导致延迟"},
            {"cause": "中间设备转发慢", "probability": 0.20,
             "description": "路由器/交换机转发性能不足"},
            {"cause": "物理距离远", "probability": 0.10,
             "description": "跨地域链路，天然延迟高"},
            {"cause": "无线链路延迟", "probability": 0.05,
             "description": "无线链路信号弱导致重传"},
        ],
        diagnostic_steps=[
            "1. 运行 traceroute 确认延迟发生在哪一跳",
            "2. 对比正常情况下的 baseline 延迟",
            "3. 检查延迟节点的端口利用率和队列长度",
            "4. 排查该链路中的流量类型和带宽占用",
            "5. 检查是否有路由策略导致非对称路径",
            "6. 使用 mtr 持续监控延迟抖动",
        ],
        recommended_actions=[
            "优化链路带宽或增加带宽",
            "优化路由路径",
            "排查抢占带宽的流量来源",
        ],
        severity=Severity.WARNING,
    ),

    # ---- Ping 延迟不稳定（抖动） ----
    DiagnosisRule(
        rule_id="ping_unstable",
        symptom_type="ping_unstable",
        trigger_condition=(
            "result.get('received', 0) > 0 and "
            "(result.get('max_rtt_ms', 0) or 0) - (result.get('min_rtt_ms', 0) or 0) > "
            "(result.get('avg_rtt_ms', 1) or 1) * 0.5"
        ),
        possible_causes=[
            {"cause": "链路干扰/不稳定", "probability": 0.35,
             "description": "无线或物理链路存在干扰"},
            {"cause": "设备队列波动", "probability": 0.30,
             "description": "设备负载不稳定导致排队波动"},
            {"cause": "带宽竞争", "probability": 0.25,
             "description": "链路存在突发流量竞争"},
            {"cause": "路由震荡", "probability": 0.10,
             "description": "路由协议收敛导致路径变化"},
        ],
        diagnostic_steps=[
            "1. 持续 ping 观察延迟抖动分布",
            "2. 检查链路物理状态",
            "3. 检查无线信号强度（WLAN 场景）",
            "4. 查看端口 CRC 错误计数",
            "5. 排查路由协议邻居关系是否稳定",
        ],
        recommended_actions=[
            "检查物理链路质量",
            "使用 mtr 持续监控延迟抖动",
        ],
        severity=Severity.WARNING,
    ),

    # ---- DNS 全部失败 ----
    DiagnosisRule(
        rule_id="dns_all_fail",
        symptom_type="dns_all_fail",
        trigger_condition="result.get('results') and all(not r.get('success', False) for r in result['results'].values())",
        possible_causes=[
            {"cause": "DNS 服务器宕机", "probability": 0.40,
             "description": "目标 DNS 服务器无响应"},
            {"cause": "网络不可达 DNS 服务器", "probability": 0.35,
             "description": "到 DNS 服务器的网络路径中断"},
            {"cause": "DNS 服务器配置错误", "probability": 0.15,
             "description": "DNS 服务器 zone 配置损坏"},
            {"cause": "域名本身不存在", "probability": 0.10,
             "description": "域名拼写错误或未注册"},
        ],
        diagnostic_steps=[
            "1. 确认域名拼写正确",
            "2. ping DNS 服务器 IP 确认可达性",
            "3. nslookup / dig 交叉验证",
            "4. dig @DNS服务器IP 域名 查看详细响应",
            "5. 查看 DNS 服务器进程和端口",
            "6. 尝试其他 DNS 服务器解析",
        ],
        recommended_actions=[
            "通知 DNS 运维检查服务器状态",
            "临时切换到公共 DNS（8.8.8.8 / 1.1.1.1）",
        ],
        severity=Severity.CRITICAL,
    ),

    # ---- DNS 慢 ----
    DiagnosisRule(
        rule_id="dns_slow",
        symptom_type="dns_slow",
        trigger_condition="any(r.get('rtt_ms', 0) > 500 for r in result.get('results', {}).values())",
        possible_causes=[
            {"cause": "DNS 服务器负载高", "probability": 0.40,
             "description": "DNS 服务器处理能力不足"},
            {"cause": "递归查询链路过远", "probability": 0.30,
             "description": "DNS 递归路径长，延迟累积"},
            {"cause": "网络延迟高", "probability": 0.20,
             "description": "到 DNS 服务器网络延迟高"},
            {"cause": "DNS 缓存失效", "probability": 0.10,
             "description": "缓存过期需要重新查询上游"},
        ],
        diagnostic_steps=[
            "1. dig +trace 查看完整解析路径和耗时",
            "2. 对比多个 DNS 服务器响应时间",
            "3. 检查 DNS 服务器 CPU/内存负载",
            "4. 查看 DNS 查询日志",
        ],
        recommended_actions=[
            "考虑使用更快的 DNS 服务器",
            "配置 DNS 缓存（如 dnsmasq）",
        ],
        severity=Severity.WARNING,
    ),

    # ---- HTTP 不可达 ----
    DiagnosisRule(
        rule_id="http_unreachable",
        symptom_type="http_unreachable",
        trigger_condition="not result.get('reachable', True)",
        possible_causes=[
            {"cause": "Web 服务宕机", "probability": 0.50,
             "description": "HTTP 服务进程崩溃或未启动"},
            {"cause": "端口被防火墙拦截", "probability": 0.25,
             "description": "防火墙规则阻止 HTTP/HTTPS 流量"},
            {"cause": "服务端口配置错误", "probability": 0.15,
             "description": "服务监听端口与预期不符"},
            {"cause": "负载均衡器故障", "probability": 0.10,
             "description": "上游负载均衡器异常"},
        ],
        diagnostic_steps=[
            "1. 确认 URL 协议和端口正确",
            "2. telnet 目标IP 80/443 测试端口连通性",
            "3. curl -v 查看详细错误信息",
            "4. 登录服务器检查服务进程",
            "5. 检查防火墙规则",
            "6. 查看服务日志",
        ],
        recommended_actions=[
            "通知 Web 服务运维",
            "检查服务器进程和端口",
            "检查防火墙规则",
        ],
        severity=Severity.WARNING,
    ),

    # ---- HTTP 慢 ----
    DiagnosisRule(
        rule_id="http_slow",
        symptom_type="http_slow",
        trigger_condition="(result.get('response_time_ms', 0) or 0) > 2000",
        possible_causes=[
            {"cause": "后端应用响应慢", "probability": 0.40,
             "description": "应用本身处理时间长（DB查询/外部API）"},
            {"cause": "数据库连接池耗尽", "probability": 0.20,
             "description": "DB 连接不足导致等待"},
            {"cause": "CDN/反向代理瓶颈", "probability": 0.15,
             "description": "代理层性能不足"},
            {"cause": "网络链路慢", "probability": 0.15,
             "description": "用户到服务器网络质量差"},
            {"cause": "服务器资源耗尽", "probability": 0.10,
             "description": "CPU/内存占满导致处理慢"},
        ],
        diagnostic_steps=[
            "1. curl -w 测量独立耗时",
            "2. 对比不同地域用户的速度差异",
            "3. 查看 Web 服务日志中的慢请求",
            "4. 检查数据库连接池和慢查询",
            "5. 查看服务器资源使用率",
            "6. 检查 CDN 命中率",
        ],
        recommended_actions=[
            "优化后端应用性能",
            "增加服务器资源",
            "启用缓存减少 DB 压力",
        ],
        severity=Severity.WARNING,
    ),

    # ---- Traceroute 超时 ----
    DiagnosisRule(
        rule_id="traceroute_timeout",
        symptom_type="traceroute_timeout",
        trigger_condition="any(str(h.get('ip', '')).strip() == '' for h in result.get('hops', []))",
        possible_causes=[
            {"cause": "中间节点禁止 ICMP", "probability": 0.45,
             "description": "中间路由器不响应 ICMP TTL 超时"},
            {"cause": "中间节点过载", "probability": 0.25,
             "description": "路由器 CPU 高导致响应慢"},
            {"cause": "链路中断", "probability": 0.20,
             "description": "某跳之后链路确实中断"},
            {"cause": "路由黑洞", "probability": 0.10,
             "description": "某跳路由器配置了黑洞路由"},
        ],
        diagnostic_steps=[
            "1. 对比历史 traceroute 结果",
            "2. ping 超时节点 IP 确认是否真不可达",
            "3. 检查是否为企业自有设备（可登录检查）",
            "4. 超时在最后一跳可能是目标禁用 ICMP",
            "5. 使用 TCP SYN traceroute 绕过 ICMP 限制",
        ],
        recommended_actions=[
            "确认超时节点是防火墙拦截还是真实中断",
            "联系运营商确认线路状态",
        ],
        severity=Severity.INFO,
    ),

    # ---- 端口全部关闭 ----
    DiagnosisRule(
        rule_id="port_all_closed",
        symptom_type="port_all_closed",
        trigger_condition="result.get('results') and all(r.get('status') == 'closed' for r in result['results'].values())",
        possible_causes=[
            {"cause": "服务未启动", "probability": 0.50,
             "description": "目标服务进程未运行"},
            {"cause": "服务端口配置变更", "probability": 0.25,
             "description": "服务监听端口被修改"},
            {"cause": "防火墙阻止", "probability": 0.20,
             "description": "iptables/ufw 阻止了端口"},
            {"cause": "端口被占用", "probability": 0.05,
             "description": "服务异常绑定端口"},
        ],
        diagnostic_steps=[
            "1. 登录服务器 netstat -tlnp 确认服务监听",
            "2. systemctl status 检查服务运行状态",
            "3. 查看服务配置文件确认端口",
            "4. iptables -L -n 检查防火墙规则",
            "5. lsof -i:端口 检查端口占用",
        ],
        recommended_actions=[
            "启动目标服务",
            "检查防火墙规则",
        ],
        severity=Severity.WARNING,
    ),
]


class DiagnosisEngine:
    """诊断引擎：匹配诊断规则，返回故障分析和排查建议"""

    def __init__(self):
        self.rules = {r.rule_id: r for r in DIAGNOSIS_RULES}

    # ------------------------------------------------------------- diagnose

    def diagnose(self, probe_type: str, target: str,
                 result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """诊断一个探测结果，返回匹配的条目（按概率排序）"""
        diagnoses = []
        for rule in self.rules.values():
            if not self._matches(rule, result):
                continue
            diagnoses.append(self._build_diagnosis(rule, target, result))

        diagnoses.sort(
            key=lambda d: d["primary_cause"]["probability"],
            reverse=True,
        )
        return diagnoses

    @staticmethod
    def _matches(rule: DiagnosisRule, result: Dict) -> bool:
        try:
            matched = eval(rule.trigger_condition, {"result": result})
            return bool(matched)
        except Exception:
            return False

    @staticmethod
    def _build_diagnosis(rule: DiagnosisRule, target: str,
                         result: Dict) -> Dict[str, Any]:
        causes = sorted(
            rule.possible_causes,
            key=lambda c: c["probability"],
            reverse=True,
        )
        primary = causes[0] if causes else {}
        return {
            "rule_id": rule.rule_id,
            "symptom_type": rule.symptom_type,
            "severity": rule.severity.value,
            "target": target,
            "timestamp": datetime.now().isoformat(),
            "primary_cause": primary,
            "possible_causes": causes,
            "diagnostic_steps": rule.diagnostic_steps,
            "recommended_actions": rule.recommended_actions,
            "probe_result_summary": DiagnosisEngine._summarize_result(result),
        }

    @staticmethod
    def _summarize_result(result: Dict) -> str:
        if result.get("avg_rtt_ms") is not None:
            loss = int((result.get("loss_rate", 0) or 0) * 100)
            return f"延迟: {result['avg_rtt_ms']}ms, 丢包: {loss}%"
        if "reachable" in result:
            return "不可达" if not result["reachable"] else "可达"
        if result.get("response_time_ms") is not None:
            return f"响应时间: {result['response_time_ms']}ms"
        return str(result)[:100]

    # ------------------------------------------------------- history batch

    def diagnose_from_history(self, agent_id: str,
                              hours: int = 24) -> List[Dict[str, Any]]:
        """基于最近告警的探测历史批量诊断"""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM probe_results
                   WHERE agent_id = ? AND created_at >= ?
                   ORDER BY created_at DESC LIMIT 100""",
                (agent_id, cutoff),
            )
            rows = cursor.fetchall()

        latest: Dict[str, Any] = {}
        for row in rows:
            key = f"{row['probe_type']}:{row['target']}"
            if key not in latest:
                latest[key] = row

        diagnoses = []
        for key, row in latest.items():
            probe_type = row["probe_type"]
            target = row["target"]
            try:
                result = ast.literal_eval(
                    row["raw_output"]) if row["raw_output"] else {}
            except Exception:
                result = {}
            diagnoses.extend(self.diagnose(probe_type, target, result))

        return diagnoses

    # ------------------------------------------------------------- rules

    def get_rules(self) -> List[Dict[str, Any]]:
        return [
            {
                "rule_id": r.rule_id,
                "symptom_type": r.symptom_type,
                "severity": r.severity.value,
                "possible_causes": r.possible_causes,
                "diagnostic_steps": r.diagnostic_steps,
            }
            for r in self.rules.values()
        ]


diagnosis_engine = DiagnosisEngine()
