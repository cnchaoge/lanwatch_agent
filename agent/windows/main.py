"""
Lanwatch Agent Windows 客户端入口文件。

两种运行模式：
1. 前台运行（调试）：python main.py
2. 安装为 Windows Service：
   - 安装：python main.py install
   - 卸载：python main.py remove
   - 启动：net start LanwatchAgent
   - 停止：net stop LanwatchAgent

v1.3.0 新增：target_runner 模式（默认）
  - 启动时从服务端拉取监控目标配置
  - 按配置执行探测并上报
  - 支持 --legacy 参数回退到旧版 ping 模式
"""
import sys, os, logging, time as time_module

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
    """前台运行的主循环（target_runner 模式，v1.3.0 默认）"""
    from core.config import load_config
    from probes.target_runner import TargetRunner

    setup_logging()
    logging.info("Lanwatch Agent 前台模式启动 [target_runner v1.3.0]")

    cfg = load_config()

    while True:
        try:
            if not cfg.agent_id:
                logging.info("等待配置 agent_id...")
                time_module.sleep(30)
                cfg.reload()
                continue

            if not cfg.agent_token:
                logging.info("等待配置 agent_token...")
                time_module.sleep(30)
                cfg.reload()
                continue

            # 创建 TargetRunner
            runner = TargetRunner(
                server_url=cfg.server_url,
                agent_id=cfg.agent_id,
                agent_token=cfg.agent_token,
                refresh_interval=300,  # 5分钟刷新一次配置
            )

            # 首次强制拉取配置
            targets = runner.fetch_targets(use_cache=True)
            if not targets:
                logging.warning("未拉取到任何监控目标，30秒后重试...")
                runner.close()
                time_module.sleep(30)
                cfg.reload()
                continue

            # 探测并上报
            results = runner.run_once()
            if results:
                runner.report_results(results)
                logging.info("本次探测 %d 个目标，上报 %d 条结果",
                             len(targets), len(results))

            runner.close()
            time_module.sleep(cfg.probe_interval)

        except KeyboardInterrupt:
            logging.info("收到停止信号，退出")
            break
        except Exception as e:
            logging.error("主循环异常: %s", e, exc_info=True)
            time_module.sleep(30)


def legacy_loop():
    """旧版 ping 模式（--legacy 参数启用）"""
    from core.config import load_config
    from core.transport import Transport
    from probes.ping import ping_results

    setup_logging()
    logging.info("Lanwatch Agent 前台模式启动 [legacy ping 模式]")
    cfg = load_config()

    while True:
        try:
            if not cfg.agent_id:
                logging.info("等待配置 agent_id...")
                time_module.sleep(30)
                cfg.reload()
                continue

            transport = Transport(cfg.server_url, cfg.agent_id, cfg.agent_token)
            reports = ping_results()
            if reports:
                ok = transport.report(reports)
                logging.info(f"上报 {len(reports)} 条，结果: {'成功' if ok else '失败'}")
            transport.close()
            time_module.sleep(cfg.probe_interval)
        except KeyboardInterrupt:
            logging.info("收到停止信号，退出")
            break
        except Exception as e:
            logging.error(f"主循环异常: {e}", exc_info=True)
            time_module.sleep(30)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("install", "remove", "start", "stop", "restart"):
        from core.service import handle_service_command
        handle_service_command()
    elif "--legacy" in sys.argv:
        ensure_config_dir()
        legacy_loop()
    else:
        ensure_config_dir()
        main_loop()