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

### Windows Agent

```powershell
cd agent/windows
pip install -r requirements.txt
python main.py             # 前台运行
# 或
python setup.py install    # 注册 Service
```

### Linux Agent

```bash
cd agent/linux
pip install -r requirements.txt
./lanwatch_agent_linux.sh start
```

### OpenWrt 路由器

```bash
上传 router_agent.sh 到 /root/
chmod +x /root/router_agent.sh
/root/router_agent.sh install
```

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
