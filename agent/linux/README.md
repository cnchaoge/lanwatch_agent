# Linux Agent

Lanwatch Agent for Linux / Ubuntu。源码版本声明为 **1.3.0**（`lanwatch_agent_linux.py` 里的 `__version__`）。这只是源码声明，不是已发布安装包。

仓库里没有 Linux 安装包，也没有 `requirements.txt`、systemd unit 或 `lanwatch_agent_linux.sh`。安装包仍是「即将上线」，不要把它当成可下载的 v1.3.0。

## 从源码运行

```bash
cd agent/linux
pip install pystray pillow   # 托盘可选；未安装时程序会跳过托盘
python3 lanwatch_agent_linux.py
```

首次运行会走设置向导，配置写到 `~/.config/lanwatch/agent.json`。

## 打包

在 `agent/linux` 目录执行（脚本文件名是 `build.sh`）：

```bash
bash build.sh
```

等价命令：

```bash
pyinstaller --onefile --name lanwatch_agent lanwatch_agent_linux.py
```

输出：`dist/lanwatch_agent`。该二进制不在 GitHub Releases 上。
