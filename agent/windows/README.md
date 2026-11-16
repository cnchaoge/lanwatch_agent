# Windows Agent

Lanwatch Agent for Windows。源码版本声明为 **1.3.0**，这不是已发布的安装包。

GitHub Releases 上最新正式版仍是 [v1.2.0](https://github.com/cnchaoge/lanwatch_agent/releases/tag/v1.2.0)（资产 `lanwatch_agent.exe`）。master 上的 1.3.0 尚未打 tag、尚未发版。

## 运行

### 前置条件

- Python 3.8+（仓库里的 `build.bat` 使用 Python 3.12）
- Windows 7+

```powershell
cd agent/windows
pip install -r requirements.txt
```

前台调试：

```powershell
python main.py
```

托盘客户端（PyInstaller 打包入口也是这个文件）：

```powershell
python lanwatch_agent.py
```

### 注册为 Windows Service（需要管理员权限和 pywin32）

仓库里没有 `setup.py`。服务命令在 `main.py`：

```powershell
python main.py install
net start LanwatchAgent
```

卸载：

```powershell
net stop LanwatchAgent
python main.py remove
```

## 配置文件

路径：`%PROGRAMDATA%\LanwatchAgent\config.json`（见 `core/config.py`）。注册向导会写入，不在仓库里。

## 打包

必须在 `agent/windows` 目录下执行。`setup/build_spec.spec` 用当前工作目录定位 `lanwatch_agent.py`、`core/`、`probes/`。PyInstaller 6 默认把产物写到该目录的 `dist/`。

```powershell
cd agent/windows
pip install -r requirements.txt
pyinstaller --noconfirm --clean --distpath dist --workpath build setup/build_spec.spec
```

或直接运行 `build.bat`（它调用的也是 `setup\build_spec.spec`）。

输出：`dist/LanwatchAgent.exe`。仓库里已经没有 `lanwatch_agent.spec`。
