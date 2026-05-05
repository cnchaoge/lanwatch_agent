#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lanwatch_agent - 企业网络监控客户端 v1.3.0

架构（v1.3.0）：
- 启动时从服务端拉取监控目标配置（targets）
- 按配置执行探测（ping / http / port / dns）
- 结果上报服务端，托盘状态实时反映网络健康状况
- 自动升级检查 + 拓扑扫描（可选）
- 完全丢弃 network_monitor.py，轻装上阵
"""
import sys
import os

# ── 自举：确保同目录模块可导入 ────────────────────────────────────
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)
os.chdir(_script_dir)

__version__ = "1.3.0"

# ═══════════════════════════════════════════════════════════════
# 内建模块
# ═══════════════════════════════════════════════════════════════
import logging
import threading
import time
import queue
import subprocess
import json
import base64
from time import sleep

# ═══════════════════════════════════════════════════════════════
# 第三方模块（打包时需要）
# ═══════════════════════════════════════════════════════════════
try:
    import httpx
except ImportError:
    httpx = None

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None

try:
    from pystray import Icon, MenuItem as MItem, Menu
except ImportError:
    Icon = None

# ═══════════════════════════════════════════════════════════════
# 项目内部模块
# ═══════════════════════════════════════════════════════════════
from core.config import Config, load_config, ensure_config_dir, get_log_path
from core.transport import Transport
from probes.target_runner import TargetRunner

# ═══════════════════════════════════════════════════════════════
# 日志
# ═══════════════════════════════════════════════════════════════
ensure_config_dir()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(get_log_path(), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("agent")

# ═══════════════════════════════════════════════════════════════
# 全局常量
# ═══════════════════════════════════════════════════════════════
PROBE_INTERVAL = 60          # 探测周期（秒）
TOPOLOGY_INTERVAL = 300      # 拓扑扫描周期（秒）
UPDATE_CHECK_INTERVAL = 86400 # 自动升级检查周期（秒）
UPDATE_DIR = os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"), "LanwatchAgent")
UPDATE_EXE = os.path.join(UPDATE_DIR, "update.exe")
UPDATE_BAT = os.path.join(UPDATE_DIR, "update.bat")
DIAG_FILE = os.path.join(_script_dir, "offline_diag.json")
GITHUB_REPO = "cnchaoge/lanwatch_agent"

# 托盘状态队列（跨线程安全）
_status_queue = queue.Queue()
_action_queue = queue.Queue()
_tray_icon_ref = None
_status_thread_started = False
_company_name = ""
_version_checked = False


# ═══════════════════════════════════════════════════════════════
# 托盘图标绘制
# ═══════════════════════════════════════════════════════════════

def _create_tray_image(color_hex: str):
    """用 PIL 绘制单色圆形托盘图标"""
    if Image is None:
        return None
    img = Image.new("RGB", (64, 64), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse([8, 8, 56, 56], fill=color_hex)
    return img


# ═══════════════════════════════════════════════════════════════
# 托盘菜单动作
# ═══════════════════════════════════════════════════════════════

def _open_log():
    """打开日志文件"""
    try:
        path = get_log_path()
        if os.path.exists(path):
            os.startfile(path) if sys.platform == "win32" else subprocess.run(["open", path])
        else:
            _show_msg("日志文件不存在")
    except Exception as e:
        _show_msg(f"打开失败: {e}")


def _show_about():
    """显示关于对话框"""
    _show_msg(f"Lanwatch Agent v{__version__}\n企业网络监控探针\n© 2026 Lanwatch")


def _show_msg(msg: str):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("Lanwatch", msg)
        root.destroy()
    except Exception:
        log.warning("[提示] %s", msg)


def _exit_app():
    """退出程序"""
    log.info("收到退出信号")
    global _tray_icon_ref
    if _tray_icon_ref:
        try:
            _tray_icon_ref.stop()
        except Exception:
            pass
    os._exit(0)


def _on_uninstall():
    """卸载服务（由后台处理）"""
    _action_queue.put_nowait(("uninstall", None))


# ═══════════════════════════════════════════════════════════════
# 卸载确认（在 Tk 主线程中处理）
# ═══════════════════════════════════════════════════════════════

def _do_uninstall_confirm():
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        if messagebox.askyesno("卸载确认", "确定要卸载 Lanwatch Agent 吗？"):
            root.destroy()
            _do_uninstall()
        else:
            root.destroy()
    except Exception:
        pass


def _do_uninstall():
    """执行卸载操作"""
    log.info("[卸载] 开始卸载...")
    try:
        cfg = load_config()
        agent_id = cfg.agent_id
        agent_token = cfg.agent_token
        if agent_id:
            transport = Transport(cfg.server_url, agent_id, agent_token)
            transport.report_offline()
            transport.close()
            log.info("[卸载] 已通知服务端")
    except Exception as e:
        log.warning("[卸载] 通知服务端失败: %s", e)
    try:
        cfg_path = os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"), "LanwatchAgent", "config.json")
        if os.path.exists(cfg_path):
            os.remove(cfg_path)
            log.info("[卸载] 配置文件已删除")
    except Exception as e:
        log.warning("[卸载] 删除配置文件失败: %s", e)
    os._exit(0)


# ═══════════════════════════════════════════════════════════════
# 托盘初始化
# ═══════════════════════════════════════════════════════════════

def setup_tray(company_name: str):
    global _tray_icon_ref, _status_thread_started, _company_name
    _company_name = company_name
    if Icon is None:
        log.warning("[托盘] pystray 未安装，托盘功能不可用")
        return None
    try:
        def make_menu():
            return Menu(
                MItem("查看日志",     lambda *_: _open_log(),    default=False),
                MItem("关于",        lambda *_: _show_about(), default=False),
                MItem("卸载服务",    lambda *_: _on_uninstall(), default=False),
                MItem("退出",        lambda *_: _exit_app(),    default=False),
            )

        icon = Icon(
            "lanwatch_agent",
            _create_tray_image("#34c759"),
            f"lanwatch ({company_name})",
            make_menu(),
        )
        _tray_icon_ref = icon

        if not _status_thread_started:
            t = threading.Thread(target=_poll_status_queue, daemon=True, name="tray_status")
            t.start()
            _status_thread_started = True

        def run_tray():
            try:
                icon.run()
            except Exception as e:
                log.error("[托盘] 运行异常: %s", e)

        t = threading.Thread(target=run_tray, daemon=True, name="tray")
        t.start()
        log.info("[托盘] 启动成功")
        return icon
    except Exception as e:
        log.warning("[托盘] 启动失败: %s", e)
        return None


def update_tray_status(is_online: bool):
    """线程安全地更新托盘状态"""
    try:
        _status_queue.put_nowait(("status", is_online))
    except Exception:
        pass


def _poll_status_queue():
    """在托盘线程中轮询状态队列，更新图标颜色"""
    global _tray_icon_ref
    current_color = None
    while True:
        try:
            op, data = _status_queue.get(timeout=1)
            if op == "status":
                color = "#34c759" if data else "#ff3b30"
                if color != current_color:
                    current_color = color
                    _do_update_tray_icon(color)
        except queue.Empty:
            continue
        except Exception as e:
            log.debug("[托盘] 状态轮询异常: %s", e)


def _do_update_tray_icon(color: str):
    """在托盘线程中安全更新图标"""
    global _tray_icon_ref, _company_name
    try:
        if _tray_icon_ref is None:
            return
        _tray_icon_ref.icon = _create_tray_image(color)
        status_text = "在线" if color == "#34c759" else "离线"
        _tray_icon_ref.title = f"lanwatch ({_company_name}) - {status_text}"
        log.info("[托盘] 状态更新: %s", color)
    except Exception as e:
        log.warning("[托盘] 更新失败: %s", e)


# ═══════════════════════════════════════════════════════════════
# 注册向导（保留，简洁有效）
# ═══════════════════════════════════════════════════════════════

def _show_setup_window():
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    win = tk.Toplevel()
    win.title("Lanwatch 网络监控 - 初始化设置")
    win.geometry("420x220")
    win.resizable(False, False)
    win.attributes("-topmost", True)

    bg = "#FFFFFF"
    accent = "#2563EB"
    muted = "#6B7280"
    border = "#E5E7EB"
    win.configure(bg=bg)

    header = tk.Label(win, text="初始化设置", font=("微软雅黑", 16, "bold"),
                     bg=bg, fg=accent)
    header.pack(pady=(20, 4))
    sub = tk.Label(win, text="填写企业名称即可完成注册", font=("微软雅黑", 9),
                  bg=bg, fg=muted)
    sub.pack()

    form = tk.Frame(win, bg=bg)
    form.pack(pady=16, padx=24, fill="x")

    tk.Label(form, text="企业名称", font=("微软雅黑", 10), bg=bg,
             fg=muted).pack(anchor="w")
    name_var = tk.StringVar()
    tk.Entry(form, textvariable=name_var, font=("微软雅黑", 11),
             bg=bg, fg="#111827", relief="solid", bd=1,
             insertbackground=accent,
             highlightthickness=1, highlightcolor=border,
             highlightbackground=border).pack(pady=(4, 16), fill="x")

    btn_frame = tk.Frame(win, bg=bg)
    btn_frame.pack(side="bottom", pady=(0, 20))

    status_lbl = tk.Label(win, text="", font=("微软雅黑", 9), bg=bg, fg=muted)
    status_lbl.pack(side="bottom", pady=(0, 8))

    register_done = threading.Event()
    result = {}

    def do_register():
        name = name_var.get().strip()
        if not name:
            status_lbl.config(text="请填写企业名称", fg="#EF4444")
            return
        status_lbl.config(text="正在注册...", fg=muted)
        win.update()
        try:
            cfg = load_config()
            transport = Transport(cfg.server_url, "", "")
            resp = transport.register({"name": name, "os_type": "windows"})
            if resp and resp.get("success"):
                cfg.set("agent_id", resp["agent_id"])
                cfg.set("agent_token", resp.get("token", ""))
                cfg.set("company_name", name)
                cfg.save()
                status_lbl.config(text=f"注册成功！Agent ID: {resp['agent_id']}", fg="#10B981")
                result["ok"] = True
                win.after(1500, lambda: win.destroy())
                win.after(1600, lambda: root.quit())
            else:
                status_lbl.config(text=f"注册失败: {resp}", fg="#EF4444")
        except Exception as e:
            status_lbl.config(text=f"注册异常: {e}", fg="#EF4444")
        finally:
            register_done.set()

    tk.Button(btn_frame, text="确认注册", command=do_register,
              font=("微软雅黑", 10, "bold"), width=10,
              bg=accent, fg="white", relief="flat", pady=7).pack(side="right")

    def on_close():
        if not result.get("ok"):
            if messagebox.askyesno("提示", "确定要退出吗？"):
                os._exit(0)
    win.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()


# ═══════════════════════════════════════════════════════════════
# 监控主循环 v1.3.0
# ═══════════════════════════════════════════════════════════════

def run_monitoring(agent_id: str, company_name: str):
    """
    监控主循环：
    - TargetRunner 拉取 targets → 探测 → 上报
    - 定期刷新配置、检查升级、扫描拓扑
    """
    global _tray_icon_ref

    cfg = load_config()
    agent_token = cfg.agent_token
    server_url = cfg.server_url

    # 首次运行立即拉取一次 targets
    topo_next_in = TOPOLOGY_INTERVAL
    upgrade_next_in = UPDATE_CHECK_INTERVAL

    while True:
        try:
            cfg.reload()
            agent_token = cfg.agent_token or os.environ.get("LANWATCH_TOKEN", "")

            runner = TargetRunner(
                server_url=server_url,
                agent_id=agent_id,
                agent_token=agent_token,
                refresh_interval=300,
            )

            targets = runner.fetch_targets(use_cache=True)
            if not targets:
                log.warning("[探测] 未拉到监控目标，%d 秒后重试...", PROBE_INTERVAL)
                runner.close()
                update_tray_status(False)
                sleep(PROBE_INTERVAL)
                continue

            results = runner.run_once()
            if results:
                ok = runner.report_results(results)
                log.info("[探测] %d 个目标，上报 %d 条: %s",
                         len(targets), len(results), "成功" if ok else "失败")
                all_ok = all(r.get("status") == "ok" for r in results)
                update_tray_status(all_ok)
                if all_ok:
                    _upload_cached_diag(agent_id, agent_token)
            else:
                update_tray_status(False)

            runner.close()

        except KeyboardInterrupt:
            log.info("收到停止信号")
            break
        except Exception as e:
            log.error("[探测] 异常: %s", e, exc_info=True)
            update_tray_status(False)

        # 定时任务
        topo_next_in -= PROBE_INTERVAL
        upgrade_next_in -= PROBE_INTERVAL
        if topo_next_in <= 0:
            topo_next_in = TOPOLOGY_INTERVAL
            # TODO: 拓扑扫描（后续独立模块）
            log.debug("[拓扑] 跳过（未实现）")
        if upgrade_next_in <= 0:
            upgrade_next_in = UPDATE_CHECK_INTERVAL
            threading.Thread(target=_check_upgrade, daemon=True, name="upgrade").start()

        sleep(PROBE_INTERVAL)

    if _tray_icon_ref:
        try:
            _tray_icon_ref.stop()
        except Exception:
            pass
    log.info("监控已停止")


# ═══════════════════════════════════════════════════════════════
# 自动升级
# ═══════════════════════════════════════════════════════════════

def _check_upgrade():
    """检查 GitHub 最新版本，必要时下载升级"""
    global _version_checked
    if _version_checked:
        return
    _version_checked = True
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"User-Agent": "lanwatch_agent"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            tag = data.get("tag_name", "").strip().lstrip("v")
            download_url = None
            for asset in data.get("assets", []):
                if asset.get("name") == "lanwatch_agent.exe":
                    download_url = asset.get("browser_download_url")
                    break
            if download_url and tag:
                cur = tuple(int(p) for p in __version__.split(".")[:3])
                new = tuple(int(p) for p in tag.split(".")[:3])
                if new > cur:
                    log.info("[升级] 发现新版本 v%s，当前 v%s", tag, __version__)
                    _do_upgrade(download_url, tag)
    except Exception as e:
        log.debug("[升级] 检查失败: %s", e)


def _parse_version(v: str):
    try:
        parts = v.strip().lstrip("v").split(".")
        return tuple(int(p) for p in parts[:3]) + (0,) * (3 - len(parts))
    except Exception:
        return (0, 0, 0)


def _do_upgrade(download_url: str, new_version: str):
    log.info("[升级] 准备下载 v%s ...", new_version)
    try:
        os.makedirs(UPDATE_DIR, exist_ok=True)
        import urllib.request
        req = urllib.request.Request(download_url, headers={"User-Agent": "lanwatch_agent"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        with open(UPDATE_EXE, "wb") as f:
            f.write(data)
        log.info("[升级] 下载完成，临时文件: %s", UPDATE_EXE)
        # 写入升级脚本
        bat = (
            "@echo off\n"
            "timeout /t 2 /nobreak > nul\n"
            f"copy /Y \"{UPDATE_EXE}\" \"{os.path.join(UPDATE_DIR, 'lanwatch_agent.exe')}\"\n"
            f'start "" "{os.path.join(UPDATE_DIR, "lanwatch_agent.exe")}"\n'
            f'del "{UPDATE_EXE}" & del "{UPDATE_BAT}"\n'
        )
        with open(UPDATE_BAT, "w", encoding="utf-8") as f:
            f.write(bat)
        log.info("[升级] 正在替换并重启...")
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            subprocess.Popen(["cmd", "/c", UPDATE_BAT],
                            startupinfo=si,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
        except Exception as e:
            log.error("[升级] 启动批处理失败: %s", e)
            return
        global _tray_icon_ref
        if _tray_icon_ref:
            try:
                _tray_icon_ref.stop()
            except Exception:
                pass
        os._exit(0)
    except Exception as e:
        log.error("[升级] 失败: %s", e)


# ═══════════════════════════════════════════════════════════════
# 离线诊断上报
# ═══════════════════════════════════════════════════════════════

def _upload_cached_diag(agent_id: str, token: str):
    """网络恢复时补传本地缓存的诊断记录"""
    if not os.path.exists(DIAG_FILE):
        return
    try:
        with open(DIAG_FILE, "r", encoding="utf-8") as f:
            diag = json.load(f)
        transport = Transport(load_config().server_url, agent_id, token)
        ok = transport.report_diag(diag)
        transport.close()
        if ok:
            os.remove(DIAG_FILE)
            log.info("[诊断] 缓存诊断已补传并清除")
    except Exception as e:
        log.warning("[诊断] 补传失败: %s", e)


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main():
    global _tray_icon_ref

    log.info("=" * 50)
    log.info("lanwatch_agent v%s 启动", __version__)
    log.info("=" * 50)

    # 隐藏控制台窗口（Windows GUI 模式）
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.ShowWindow(
                ctypes.windll.kernel32.GetConsoleWindow(), 0
            )
        except Exception:
            pass

    # 确保升级目录存在
    os.makedirs(UPDATE_DIR, exist_ok=True)

    cfg = load_config()

    # ── 未注册：引导注册 ──
    if not cfg.agent_id:
        log.info("首次运行，显示注册向导...")
        _show_setup_window()
        cfg.reload()
        if not cfg.agent_id:
            log.warning("注册未完成，程序退出")
            return

    agent_id = cfg.agent_id
    company_name = cfg.get("company_name", "")
    log.info("已配置 Agent ID: %s", agent_id)

    # ── 托盘 ──
    if _tray_icon_ref is None:
        setup_tray(company_name)

    # ── 启动监控主循环（独立线程） ──
    monitor_thread = threading.Thread(
        target=run_monitoring,
        args=(agent_id, company_name),
        daemon=True,
        name="monitor",
    )
    monitor_thread.start()

    # ── 保持主线程存活 ──
    monitor_thread.join()
    log.info("Agent 已停止")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        with open(get_log_path(), "a", encoding="utf-8") as f:
            f.write(f"\n[FATAL] main() crashed: {e}\n{traceback.format_exc()}\n")
        os._exit(1)
