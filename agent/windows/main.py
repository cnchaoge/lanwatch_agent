"""
Lanwatch Agent Windows 客户端入口文件。

两种运行模式：
1. 前台运行（调试）：python main.py
2. 安装为 Windows Service：
   - 安装：python main.py install
   - 卸载：python main.py remove
   - 启动：net start LanwatchAgent
   - 停止：net stop LanwatchAgent
"""
import sys, os, logging

# 确保项目路径在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import load_config, ensure_config_dir, get_log_path, CONFIG_DIR


def setup_logging():
    """配置日志（前台运行模式）"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(get_log_path(), encoding="utf-8"),
            logging.StreamHandler()
        ]
    )


def main_loop():
    """前台运行的主循环（调试用）"""
    from core.config import load_config
    from core.transport import Transport
    from probes.ping import ping_results
    import time

    setup_logging()
    logging.info("Lanwatch Agent 前台模式启动")
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
    if len(sys.argv) > 1 and sys.argv[1] in ("install", "remove", "start", "stop", "restart"):
        from core.service import handle_service_command
        handle_service_command()
    else:
        ensure_config_dir()
        main_loop()
