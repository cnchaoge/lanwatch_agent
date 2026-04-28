"""
Windows Service 封装：
- 使用 win32serviceutil 注册为 Windows 服务
- 支持安装/卸载/启动/停止
- 服务主循环含进程守护逻辑
"""
import os, sys, time, logging, threading


def setup_logging():
    """配置日志输出到文件"""
    from .config import get_log_path, CONFIG_DIR
    os.makedirs(CONFIG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(get_log_path(), encoding="utf-8"),
            logging.StreamHandler()
        ]
    )


try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    WINDOWS_SERVICE_AVAILABLE = True
except ImportError:
    WINDOWS_SERVICE_AVAILABLE = False


class LanwatchService:
    """
    Lanwatch Agent Windows Service 主类。

    使用方式：
    - 安装服务：python service.py install
    - 卸载服务：python service.py remove
    - 启动服务：net start LanwatchAgent
    - 停止服务：net stop LanwatchAgent
    """
    _svc_name_ = "LanwatchAgent"
    _svc_display_name_ = "Lanwatch Network Monitor"
    _svc_description_ = "企业网络监控探针，自动探测网络状态并上报"

    def __init__(self, args):
        self.stop_event = threading.Event()
        self.main_loop_thread = None

    def SvcStop(self):
        """服务停止"""
        logging.info("收到停止信号，正在停止服务...")
        self.stop_event.set()
        if self.main_loop_thread and self.main_loop_thread.is_alive():
            self.main_loop_thread.join(timeout=10)
        logging.info("服务已停止")

    def SvcDoRun(self):
        """服务主入口"""
        servicemanager.LogInfoMsg(f"{self._svc_display_name_} 服务启动")
        logging.info("Lanwatch Agent Service 启动")
        try:
            self.main_loop()
        except Exception as e:
            logging.error(f"Service main_loop 异常: {e}", exc_info=True)
            servicemanager.LogErrorMsg(f"Service 异常: {e}")

    def main_loop(self):
        """
        主循环：
        1. 加载配置
        2. 注册/连接服务器
        3. 执行探测 → 上报 → 等待 → 循环
        4. 进程守护（异常自动重启）
        """
        from .config import load_config
        from .transport import Transport

        cfg = load_config()
        max_retries = 5
        retry_count = 0

        while not self.stop_event.is_set():
            try:
                # 确保 agent_id 有效
                if not cfg.agent_id:
                    logging.info("agent_id 为空，尝试注册...")
                    transport = Transport(cfg.server_url, "pending", cfg.agent_token)
                    payload = {
                        "agent_id": _get_fallback_agent_id(),
                        "name": _get_hostname(),
                        "ip": _get_local_ip(),
                        "os_type": "windows",
                        "interval": cfg.probe_interval
                    }
                    result = transport.register(payload)
                    if result and result.get("agent_token"):
                        cfg.set("agent_token", result["agent_token"])
                        cfg.set("agent_id", result.get("agent_id", payload["agent_id"]))
                        cfg.save()
                        logging.info(f"注册成功，agent_id={cfg.agent_id}")
                    else:
                        logging.warning("注册失败，使用临时 ID")
                        cfg.set("agent_id", _get_fallback_agent_id())
                        cfg.save()
                    transport.close()
                    retry_count = 0

                # 创建 transport
                transport = Transport(cfg.server_url, cfg.agent_id, cfg.agent_token)

                # 主探测循环
                while not self.stop_event.is_set():
                    loop_start = time.time()
                    reports = []

                    # 执行探测
                    if "ping" in cfg.enabled_probes:
                        from ..probes.ping import ping_results
                        reports.extend(ping_results())

                    if "snmp" in cfg.enabled_probes:
                        from ..probes.snmp import snmp_results
                        reports.extend(snmp_results(cfg))

                    # 上报
                    if reports:
                        ok = transport.report(reports)
                        if ok:
                            logging.debug(f"上报成功，共 {len(reports)} 条")
                        else:
                            logging.warning(f"上报失败")

                    # 计算睡眠时间
                    elapsed = time.time() - loop_start
                    sleep_time = max(1, cfg.probe_interval - elapsed)
                    if self.stop_event.wait(sleep_time):
                        break

                transport.close()
                retry_count = 0

            except Exception as e:
                logging.error(f"主循环异常: {e}", exc_info=True)
                retry_count += 1
                if retry_count >= max_retries:
                    logging.error(f"连续失败 {max_retries} 次，停止服务")
                    break
                wait_time = min(60, 2 ** retry_count)  # 指数退避，最多60秒
                logging.info(f"{wait_time} 秒后重试...")
                self.stop_event.wait(wait_time)


def _get_hostname() -> str:
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "unknown"


def _get_local_ip() -> str:
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _get_fallback_agent_id() -> str:
    return f"PC-{_get_hostname()}"


def handle_service_command():
    """处理 Service 命令行参数"""
    if len(sys.argv) == 1:
        # 无参数：交互式运行（调试用）
        setup_logging()
        logging.info("以交互模式启动（调试用），按 Ctrl+C 停止")
        try:
            interactive_main_loop()
        except KeyboardInterrupt:
            logging.info("已停止")
    else:
        # Service 命令：install / remove / start / stop
        win32serviceutil.HandleCommandLine(LanwatchService)


def interactive_main_loop():
    """交互式运行主循环（调试用）"""
    from .config import load_config
    from .transport import Transport
    from ..probes.ping import ping_results
    import time

    setup_logging()
    logging.info("Lanwatch Agent 交互模式启动")
    cfg = load_config()

    while True:
        try:
            if not cfg.agent_id:
                logging.info("等待配置 agent_id...")
                time.sleep(30)
                cfg.reload()
                continue

            transport = Transport(cfg.server_url, cfg.agent_id, cfg.agent_token)
            reports = ping_results()
            if reports:
                ok = transport.report(reports)
                logging.info(f"上报 {len(reports)} 条，结果: {'成功' if ok else '失败'}")
            transport.close()
            time.sleep(cfg.probe_interval)
        except KeyboardInterrupt:
            logging.info("收到停止信号，退出")
            break
        except Exception as e:
            logging.error(f"主循环异常: {e}", exc_info=True)
            time.sleep(30)


if __name__ == "__main__":
    handle_service_command()
