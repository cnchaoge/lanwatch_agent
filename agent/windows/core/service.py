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
        主循环 v1.3.0：
        1. 加载配置
        2. 通过 TargetRunner 拉取服务端监控目标
        3. 执行探测 → 上报 → 等待 → 循环
        4. 进程守护（异常自动重启）
        """
        from ..probes.target_runner import TargetRunner
        from .config import load_config

        cfg = load_config()
        max_retries = 5
        retry_count = 0

        while not self.stop_event.is_set():
            try:
                if not cfg.agent_id:
                    logging.info("agent_id 为空，等待配置...")
                    self.stop_event.wait(30)
                    cfg.reload()
                    continue

                runner = TargetRunner(
                    server_url=cfg.server_url,
                    agent_id=cfg.agent_id,
                    agent_token=cfg.agent_token,
                    refresh_interval=300,
                )

                targets = runner.fetch_targets(use_cache=True)
                if not targets:
                    logging.warning("未拉取到监控目标，30秒后重试...")
                    runner.close()
                    self.stop_event.wait(30)
                    cfg.reload()
                    continue

                while not self.stop_event.is_set():
                    results = runner.run_once()
                    if results:
                        ok = runner.report_results(results)
                        logging.info("探测 %d 个目标，上报 %d 条结果: %s",
                                     len(targets), len(results), "成功" if ok else "失败")
                    runner.close()
                    if self.stop_event.wait(cfg.probe_interval):
                        break
                    cfg.reload()  # 重新加载配置（可能 token 已更新）

                retry_count = 0

            except Exception as e:
                logging.error("主循环异常: %s", e, exc_info=True)
                retry_count += 1
                if retry_count >= max_retries:
                    logging.error("连续失败 %d 次，停止服务", max_retries)
                    break
                wait_time = min(60, 2 ** retry_count)
                logging.info("%d 秒后重试...", wait_time)
                self.stop_event.wait(wait_time)

        logging.info("服务已停止")


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
    """交互式运行主循环 v1.3.0（调试用）— 使用 TargetRunner"""
    from .config import load_config
    from ..probes.target_runner import TargetRunner
    import time

    setup_logging()
    logging.info("Lanwatch Agent 交互模式启动 [TargetRunner]")
    cfg = load_config()

    while True:
        try:
            if not cfg.agent_id:
                logging.info("等待配置 agent_id...")
                time.sleep(30)
                cfg.reload()
                continue

            runner = TargetRunner(
                server_url=cfg.server_url,
                agent_id=cfg.agent_id,
                agent_token=cfg.agent_token,
                refresh_interval=300,
            )
            targets = runner.fetch_targets(use_cache=True)
            if not targets:
                logging.warning("未拉取到监控目标，30秒后重试...")
                runner.close()
                time.sleep(30)
                cfg.reload()
                continue

            results = runner.run_once()
            if results:
                ok = runner.report_results(results)
                logging.info("探测 %d 个目标，上报 %d 条结果: %s",
                             len(targets), len(results), "成功" if ok else "失败")
            runner.close()
            time.sleep(cfg.probe_interval)
        except KeyboardInterrupt:
            logging.info("收到停止信号，退出")
            break
        except Exception as e:
            logging.error("主循环异常: %s", e, exc_info=True)
            time.sleep(30)


if __name__ == "__main__":
    handle_service_command()
