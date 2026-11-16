# 安装指南

## 方式一：Docker 部署（推荐）

### 1. 安装 Docker

```bash
# Linux
curl -fsSL https://get.docker.com | bash

# Windows: 下载 Docker Desktop
# https://www.docker.com/products/docker-desktop
```

### 2. 启动服务

```bash
git clone https://github.com/cnchaoge/lanwatch_agent.git
cd lanwatch_agent
docker-compose up -d
```

访问 http://localhost:8000

## 方式二：直接部署

### Linux/macOS

```bash
# 1. 克隆代码
git clone https://github.com/cnchaoge/lanwatch_agent.git
cd lanwatch_agent/server

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
export SCKEY=你的Server酱Key
export ADMIN_PASSWORD=你的密码

# 4. 启动
python main.py
```

### Windows

```powershell
# 1. 安装 Python 3.9+
# https://www.python.org/downloads/windows/

# 2. 克隆代码
git clone https://github.com/cnchaoge/lanwatch_agent.git
cd lanwatch_agent/server

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
$env:SCKEY="你的Server酱Key"
$env:ADMIN_PASSWORD="你的密码"

# 5. 启动
python main.py
```

## 部署 Agent

最新已发布的安装包是 Windows **v1.2.0**（[Release](https://github.com/cnchaoge/lanwatch_agent/releases/tag/v1.2.0) 的 `lanwatch_agent.exe`）。源码版本 1.3.0 在 `master`，尚未打 tag、尚未发版。Linux、macOS、OpenWrt 都没有现成安装包。

### Windows Agent

仓库里没有 `setup.py`，也没有 `lanwatch_agent.spec`。

```powershell
cd agent/windows
pip install -r requirements.txt
python main.py                 # 前台运行
python lanwatch_agent.py       # 托盘客户端
python main.py install         # 注册 Windows Service（需管理员和 pywin32）
net start LanwatchAgent
```

打包（工作目录必须是 `agent/windows`，产物 `dist/LanwatchAgent.exe`）：

```powershell
pyinstaller --noconfirm --clean --distpath dist --workpath build setup/build_spec.spec
```

也可以运行 `agent/windows/build.bat`。

### Linux Agent

没有 `requirements.txt`，也没有 systemd 单元。安装包即将上线。

```bash
cd agent/linux
pip install pystray pillow
python3 lanwatch_agent_linux.py
```

本地打包：`bash build.sh`，输出 `dist/lanwatch_agent`。

### macOS Agent

源码在 `agent/mac/lanwatch_agent_mac.py`，版本声明 1.3.0。尚未提供安装包。

```bash
cd agent/mac
pip install pystray pillow
python3 lanwatch_agent_mac.py
```

本地打包（工作目录为 `agent/mac`）：

```bash
pyinstaller --noconfirm --clean lanwatch_agent_mac.spec
```

### OpenWrt 路由器

安装包即将上线。源码安装入口是 `agent/router/install.sh`，不是 `router_agent.sh install`（主脚本没有 `install` 子命令）。

```bash
scp -r agent/router root@192.168.1.1:/tmp/lanwatch
ssh root@192.168.1.1
cd /tmp/lanwatch
sh install.sh
```

详见 `agent/router/README.md`。

## 生产环境配置

### Nginx 反向代理

```nginx
server {
    listen 80;
    server_name lanwatch.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### HTTPS（Let's Encrypt）

```bash
certbot --nginx -d lanwatch.example.com
```

### 防火墙

```bash
# Linux
ufw allow 8000/tcp

# Windows: 在「高级防火墙」Inbound Rules 添加 8000 端口
```
