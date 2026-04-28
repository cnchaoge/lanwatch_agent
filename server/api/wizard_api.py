"""引导式故障排查向导 API"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from enum import Enum
from datetime import datetime
import uuid

router = APIRouter()


class 故障场景(str, Enum):
    网络_设备不可达 = "net_unreachable"
    网络_延迟高 = "net_high_latency"
    网络_丢包 = "net_packet_loss"
    DNS_解析失败 = "dns_failure"
    DNS_解析慢 = "dns_slow"
    HTTP_访问异常 = "http_error"
    应用_服务无响应 = "service_down"


class WizardStep(BaseModel):
    step_id: str
    question: str
    step_type: str  # choice | yesno | input
    options: Optional[List[str]] = None
    hint: Optional[str] = None
    commands: Optional[List[str]] = None


# ===== 场景排查树 =====

WIZARD_SCENARIOS: Dict[str, Dict[str, Any]] = {

    故障场景.网络_设备不可达.value: {
        "title": "🔌 设备不可达排查",
        "description": "目标主机 ping 不通，逐步定位故障点",
        "first_step": "net_1",
        "steps": {
            "net_1": WizardStep(
                step_id="net_1",
                question="请问您是从哪个位置 ping 不通目标 IP 的？",
                step_type="choice",
                options=["从我自己的电脑/服务器", "从网络监控平台（另一个网段）",
                         "从同一交换机的其他设备"],
                hint="这能帮助确定故障范围",
            ),
            "net_1_a": WizardStep(
                step_id="net_1_a",
                question="目标 IP 是不是 192.168.x.x 或 10.x.x.x 等内网地址？",
                step_type="yesno",
                hint="私网地址无法从公网直接 ping",
            ),
            "net_1_b": WizardStep(
                step_id="net_1_b",
                question="请描述一下您的网络环境：",
                step_type="choice",
                options=["同一栋楼/同一个交换机", "跨楼层/跨交换机", "跨地区/跨机房"],
                hint="不同范围排查路径不同",
            ),
            "net_2": WizardStep(
                step_id="net_2",
                question="能否 traceroute（Linux: traceroute, Windows: tracert）到目标 IP，看到哪一跳超时？",
                step_type="input",
                hint="在命令行执行: traceroute <目标IP>（Linux）或 tracert <目标IP>（Windows），把结果贴过来",
            ),
            "net_2_none": WizardStep(
                step_id="net_2_none",
                question="traceroute 直接超时，没有任何节点返回？",
                step_type="yesno",
                hint="完全超时通常是出口路由器问题或链路断了",
            ),
            "net_3": WizardStep(
                step_id="net_3",
                question="请尝试 ping 同网段的其他 IP（如网关 192.168.1.1 或 8.8.8.8），能否 ping 通？",
                step_type="choice",
                options=["网关能通", "8.8.8.8 能通，同一网段其他 IP 不通", "全部不通"],
                hint="这能判断是本机问题、局域网问题还是出口问题",
            ),
            "net_3_a": WizardStep(
                step_id="net_3_a",
                question="网关通，其他同网段 IP 不通。请问目标 IP 和您的 IP 在同一网段吗？",
                step_type="yesno",
                hint="检查子网掩码，例如 192.168.1.10 和 192.168.1.200 通常同网段",
            ),
            "net_final_router": WizardStep(
                step_id="net_final_router",
                question="根据您提供的信息，最可能的原因是：目标设备宕机或网关路由问题。建议操作：\n1. 联系机房确认目标设备电源状态\n2. 登录网关路由器检查是否有到目标 IP 的路由\n3. 登录目标设备所属的交换机，检查端口状态",
                step_type="input",
                hint="请确认是否需要生成故障工单？",
            ),
            "net_final_same_subnet": WizardStep(
                step_id="net_final_same_subnet",
                question="根据排查结果，建议执行以下操作：\n1. 检查目标设备网线是否脱落\n2. 在交换机上查看该 MAC 地址对应的端口\n3. 确认该端口是否处于 blocking 状态（STP）\n4. 尝试更换网线",
                step_type="input",
                hint="问题解决了吗？",
            ),
            "net_final_local": WizardStep(
                step_id="net_final_local",
                question="本地网络问题。建议：\n1. 检查本机防火墙是否阻止 ping\n2. 检查本机网络配置（IP/子网掩码/网关）\n3. 重启本机网络服务",
                step_type="input",
                hint="问题解决了吗？",
            ),
        },
        "transitions": {
            "net_1": {"从我自己的电脑/服务器": "net_1_a",
                      "从网络监控平台（另一个网段）": "net_1_b",
                      "从同一交换机的其他设备": "net_3"},
            "net_1_a": {"是": "net_final_local", "否": "net_1_b"},
            "net_1_b": {"同一栋楼/同一个交换机": "net_3",
                        "跨楼层/跨交换机": "net_3",
                        "跨地区/跨机房": "net_2"},
            "net_2": {},
            "net_2_none": {"是": "net_final_router", "否": "net_3"},
            "net_3": {"网关能通": "net_3_a",
                      "8.8.8.8 能通，同一网段其他 IP 不通": "net_3_a",
                      "全部不通": "net_1_a"},
            "net_3_a": {"是": "net_final_same_subnet", "否": "net_final_router"},
        },
    },

    故障场景.网络_延迟高.value: {
        "title": "📶 网络延迟高排查",
        "description": "网络 ping 延迟明显偏高，定位瓶颈",
        "first_step": "lat_1",
        "steps": {
            "lat_1": WizardStep(
                step_id="lat_1",
                question="延迟大概是多少？",
                step_type="choice",
                options=["100-200ms（略高）", "200-500ms（明显高）", "500ms+（严重高）"],
                hint="正常国内骨干网络延迟在 20-100ms",
            ),
            "lat_2": WizardStep(
                step_id="lat_2",
                question="延迟是持续高，还是有时高有时正常（抖动）？",
                step_type="choice",
                options=["持续高", "时高时低，波动大"],
                hint="持续高 = 带宽占满；抖动大 = 拥塞或干扰",
            ),
            "lat_3": WizardStep(
                step_id="lat_3",
                question="请执行 mtr 或 traceroute 到目标 IP，观察哪一跳延迟突然增高？",
                step_type="input",
                hint="Linux: mtr <IP> | Windows: mtr <IP> 或 tracert <IP>",
            ),
            "lat_3_normal": WizardStep(
                step_id="lat_3_normal",
                question="traceroute 各跳延迟都正常吗？",
                step_type="yesno",
                hint="如果所有跳都高，问题在出口带宽或本机",
            ),
            "lat_final_bandwidth": WizardStep(
                step_id="lat_final_bandwidth",
                question="高延迟很可能由链路带宽占满引起。建议排查：\n1. 检查该链路上的流量监控（是否有大流量占用）\n2. 查看路由器接口带宽利用率\n3. 如果是 VPN，检查 VPN 隧道的带宽限制\n4. 联系运营商确认线路状态",
                step_type="input",
                hint="问题解决了吗？",
            ),
            "lat_final_local": WizardStep(
                step_id="lat_final_local",
                question="建议执行以下排查：\n1. 检查本机是否有人大量下载/上传\n2. 检查本机网络接口是否有大量错误包（netstat -i）\n3. 尝试更换网络路径（不同 WiFi/有线）测试",
                step_type="input",
                hint="问题解决了吗？",
            ),
        },
        "transitions": {
            "lat_1": {"100-200ms（略高）": "lat_2",
                      "200-500ms（明显高）": "lat_2",
                      "500ms+（严重高）": "lat_2"},
            "lat_2": {"持续高": "lat_3", "时高时低，波动大": "lat_3"},
            "lat_3": {},
            "lat_3_normal": {"是": "lat_final_local", "否": "lat_final_bandwidth"},
        },
    },

    故障场景.DNS_解析失败.value: {
        "title": "🌐 DNS 解析失败排查",
        "description": "域名无法解析，定位 DNS 问题",
        "first_step": "dns_1",
        "steps": {
            "dns_1": WizardStep(
                step_id="dns_1",
                question="请问是所有网站都打不开，还是只是个别域名？",
                step_type="choice",
                options=["所有网站都打不开", "只有某些特定域名打不开"],
                hint="全部不行 = DNS 配置或网络问题；个别不行 = 域名本身问题",
            ),
            "dns_1_all": WizardStep(
                step_id="dns_1_all",
                question="请 ping 8.8.8.8 确认网络是否通畅",
                step_type="yesno",
                hint="8.8.8.8 是 Google 的 DNS/IP，如果这个能 ping 通说明网络没问题",
            ),
            "dns_2": WizardStep(
                step_id="dns_2",
                question="请尝试以下命令查看 DNS 配置：\nLinux: cat /etc/resolv.conf\nWindows: ipconfig /all | findstr DNS\n\nDNS 服务器 IP 是什么？",
                step_type="input",
                hint="常见的 DNS: 8.8.8.8 / 1.1.1.1 / 运营商 DNS",
            ),
            "dns_3": WizardStep(
                step_id="dns_3",
                question="请尝试 nslookup 或 dig 命令解析域名：\nnslookup <域名>\n或 dig <域名>\n\n返回什么结果？",
                step_type="input",
                hint="返回 SERVFAIL = DNS 服务器故障；返回 NXDOMAIN = 域名不存在",
            ),
            "dns_final_network": WizardStep(
                step_id="dns_final_network",
                question="网络正常但 DNS 不通。建议：\n1. 更换 DNS 服务器为 8.8.8.8 或 1.1.1.1\n2. 检查 /etc/resolv.conf 或 DNS 配置\n3. 联系网络管理员确认 DNS 服务状态",
                step_type="input",
                hint="问题解决了吗？",
            ),
            "dns_final_server": WizardStep(
                step_id="dns_final_server",
                question="DNS 服务器本身有问题。建议：\n1. 临时更换 DNS 为公共 DNS（8.8.8.8）\n2. 通知 DNS 管理员检查服务器状态\n3. 查看 DNS 服务器日志定位根因",
                step_type="input",
                hint="问题解决了吗？",
            ),
        },
        "transitions": {
            "dns_1": {"所有网站都打不开": "dns_1_all",
                      "只有某些特定域名打不开": "dns_3"},
            "dns_1_all": {"是": "dns_final_network", "否": "dns_final_network"},
            "dns_2": {},
            "dns_3": {},
        },
    },

    故障场景.HTTP_访问异常.value: {
        "title": "🌍 HTTP/Web 访问异常排查",
        "description": "网站或 Web 服务无法访问",
        "first_step": "http_1",
        "steps": {
            "http_1": WizardStep(
                step_id="http_1",
                question="HTTP 访问返回什么状态码或错误？",
                step_type="choice",
                options=["连接超时/无法连接", "返回 4xx 错误（403/404/502/503）",
                         "返回空白页面或连接重置"],
                hint="不同错误代表不同问题",
            ),
            "http_2": WizardStep(
                step_id="http_2",
                question="请在命令行执行以下命令，把结果贴过来：\ncurl -v <URL>\n或\ntelnet <主机> <端口>",
                step_type="input",
                hint="curl -v 会显示完整的请求和响应过程",
            ),
            "http_final_502": WizardStep(
                step_id="http_final_502",
                question="502 Bad Gateway 通常是上游服务宕机。建议：\n1. 检查后端应用进程是否存活\n2. 检查负载均衡器配置\n3. 查看应用错误日志\n4. 确认后端服务端口是否正常监听",
                step_type="input",
                hint="问题解决了吗？",
            ),
            "http_final_connect": WizardStep(
                step_id="http_final_connect",
                question="连接超时可能原因：\n1. 服务进程未运行\n2. 防火墙阻止了端口\n3. 端口配置错误\n4. 服务过载拒绝连接\n\n建议检查：systemctl status nginx/apache，检查防火墙规则 iptables -L",
                step_type="input",
                hint="问题解决了吗？",
            ),
            "http_final_dns": WizardStep(
                step_id="http_final_dns",
                question="DNS 解析问题导致无法访问。建议：\n1. ping 域名确认是否解析到正确 IP\n2. nslookup 域名 交叉验证\n3. 确认 DNS 解析是否变更",
                step_type="input",
                hint="问题解决了吗？",
            ),
        },
        "transitions": {
            "http_1": {"连接超时/无法连接": "http_2",
                       "返回 4xx 错误（403/404/502/503）": "http_final_502",
                       "返回空白页面或连接重置": "http_2"},
            "http_2": {},
        },
    },

    故障场景.应用_服务无响应.value: {
        "title": "🖥️ 服务无响应排查",
        "description": "服务器上的服务进程无响应",
        "first_step": "svc_1",
        "steps": {
            "svc_1": WizardStep(
                step_id="svc_1",
                question="服务是否完全无法连接，还是响应很慢？",
                step_type="choice",
                options=["完全无法连接", "能连接但响应很慢", "间歇性无响应"],
                hint="不同情况排查方向不同",
            ),
            "svc_2": WizardStep(
                step_id="svc_2",
                question="请执行以下命令检查服务状态：\nLinux: systemctl status <服务名>\n或 ps aux | grep <服务名>\nWindows: sc query <服务名>\n或 Get-Service <服务名>\n\n服务状态是什么？",
                step_type="input",
                hint="服务名例如 nginx / mysql / redis / httpd",
            ),
            "svc_3": WizardStep(
                step_id="svc_3",
                question="请检查服务日志：\nLinux: journalctl -u <服务名> -n 50\n或 tail -50 /var/log/<服务名>/error.log\nWindows: 事件查看器 > 应用程序日志\n\n是否有错误信息？",
                step_type="input",
                hint="日志中最常见的错误：OOM（内存不足）、端口被占用、配置文件错误",
            ),
            "svc_final_down": WizardStep(
                step_id="svc_final_down",
                question="服务进程已停止。建议：\n1. systemctl start <服务名> 启动服务\n2. 查看日志找到崩溃原因\n3. 检查系统资源（内存/磁盘/CPU）\n4. 如果是 OOM，调整服务内存限制或增加物理内存",
                step_type="input",
                hint="问题解决了吗？",
            ),
            "svc_final_slow": WizardStep(
                step_id="svc_final_slow",
                question="服务响应慢可能原因：\n1. CPU/内存负载高（top / htop 检查）\n2. 数据库连接池耗尽\n3. 磁盘 I/O 高\n4. 外部 API 调用慢\n\n建议检查：top、iotop、ss -s 查看连接数",
                step_type="input",
                hint="问题解决了吗？",
            ),
        },
        "transitions": {
            "svc_1": {"完全无法连接": "svc_2",
                      "能连接但响应很慢": "svc_final_slow",
                      "间歇性无响应": "svc_3"},
            "svc_2": {},
            "svc_3": {},
        },
    },
}

_TERMINAL_STEPS = frozenset({
    "net_2", "lat_3", "dns_2", "dns_3", "http_2", "svc_2", "svc_3",
    "net_final_router", "net_final_same_subnet", "net_final_local",
    "lat_final_bandwidth", "lat_final_local",
    "dns_final_network", "dns_final_server",
    "http_final_502", "http_final_connect", "http_final_dns",
    "svc_final_down", "svc_final_slow",
})


class WizardSession:
    """向导会话"""

    def __init__(self, session_id: str, scenario_id: str):
        self.session_id = session_id
        self.scenario_id = scenario_id
        self.current_step: Optional[str] = None
        self.answers: Dict[str, str] = {}
        self.started_at = datetime.now().isoformat()
        self.finished = False
        scenario = WIZARD_SCENARIOS.get(scenario_id, {})
        self.first_step = scenario.get("first_step", "")

    def get_current_step(self) -> Optional[WizardStep]:
        if not self.current_step and self.first_step:
            self.current_step = self.first_step
        scenario = WIZARD_SCENARIOS.get(self.scenario_id, {})
        steps = scenario.get("steps", {})
        if self.current_step:
            return steps.get(self.current_step)
        return None

    def answer(self, response: str) -> Optional[WizardStep]:
        """处理用户回答，进入下一步"""
        scenario = WIZARD_SCENARIOS.get(self.scenario_id, {})
        transitions = scenario.get("transitions", {})

        self.answers[self.current_step] = response

        if self.current_step in transitions:
            options_map = transitions[self.current_step]
            next_step = options_map.get(response)
            if next_step:
                self.current_step = next_step

        return self.get_current_step()


# 内存中的会话存储（生产环境建议用 Redis）
_sessions: Dict[str, WizardSession] = {}


# ===== API =====

@router.get("/wizard/scenarios")
async def list_scenarios():
    """列出所有排查场景"""
    scenarios = []
    for scenario_id, info in WIZARD_SCENARIOS.items():
        scenarios.append({
            "id": scenario_id,
            "title": info["title"],
            "description": info["description"],
        })
    return {"scenarios": scenarios}


@router.post("/wizard/start")
async def start_wizard(scenario_id: str = Query(...)):
    """启动排查向导"""
    if scenario_id not in WIZARD_SCENARIOS:
        raise HTTPException(status_code=404, detail="未知场景")

    session_id = str(uuid.uuid4())[:8]
    session = WizardSession(session_id, scenario_id)
    first_step = session.get_current_step()

    _sessions[session_id] = session

    return {
        "session_id": session_id,
        "scenario": WIZARD_SCENARIOS[scenario_id]["title"],
        "step": {
            "step_id": first_step.step_id,
            "question": first_step.question,
            "step_type": first_step.step_type,
            "options": first_step.options,
            "hint": first_step.hint,
        },
    }


@router.post("/wizard/{session_id}/answer")
async def answer_step(session_id: str, response: str = Query(...)):
    """回答当前步骤，进入下一步"""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    session = _sessions[session_id]

    # 记录并检查是否终端步骤
    session.answers[session.current_step] = response

    if session.current_step in _TERMINAL_STEPS:
        session.finished = True
        return {
            "session_id": session_id,
            "finished": True,
            "message": "排查向导已结束。如需进一步帮助请联系运维人员。",
            "summary": session.answers,
        }

    next_step = session.answer(response)

    if next_step is None or session.finished:
        session.finished = True
        return {
            "session_id": session_id,
            "finished": True,
            "message": "排查完成。如果问题未解决，建议联系运维人员进一步分析。",
            "summary": session.answers,
        }

    return {
        "session_id": session_id,
        "finished": False,
        "step": {
            "step_id": next_step.step_id,
            "question": next_step.question,
            "step_type": next_step.step_type,
            "options": next_step.options,
            "hint": next_step.hint,
        },
    }


@router.get("/wizard/{session_id}/status")
async def get_session_status(session_id: str):
    """查询会话状态"""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    session = _sessions[session_id]
    return {
        "session_id": session_id,
        "scenario_id": session.scenario_id,
        "current_step": session.current_step,
        "finished": session.finished,
        "started_at": session.started_at,
        "answers_count": len(session.answers),
    }
