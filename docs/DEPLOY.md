# LANWatch 部署文档

> 完整的部署、运维、故障排查指南。从零搭建一个生产级 LANWatch SaaS 平台。

---

## 目录

0. [架构概述](#0-架构概述)
1. [服务器准备](#1-服务器准备)
2. [域名与 DNS](#2-域名与-dns)
3. [SSH 密钥配置](#3-ssh-密钥配置)
4. [Docker 安装与镜像加速](#4-docker-安装与镜像加速)
5. [代码部署](#5-代码部署)
6. [环境变量配置（隐私脱敏）](#6-环境变量配置隐私脱敏)
7. [Dockerfile 优化（中国服务器）](#7-dockerfile-优化中国服务器)
8. [启动服务](#8-启动服务)
9. [Nginx 反向代理](#9-nginx-反向代理)
10. [SSL 证书](#10-ssl-证书)
11. [腾讯云 Lighthouse 防火墙](#11-腾讯云-lighthouse-防火墙)
12. [端到端验证](#12-端到端验证)
13. [常用运维命令](#13-常用运维命令)
14. [数据备份与恢复](#14-数据备份与恢复)
15. [故障排查](#15-故障排查)

---

## 0. 架构概述

```
┌────────────────────────────────────────────────┐
│  客户端（企业内网）                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Windows  │  │  Linux   │  │ OpenWRT  │       │
│  │  Agent   │  │  Agent   │  │  Agent   │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       └──────────────┼──────────────┘            │
└─────────────────────┼───────────────────────────┘
                      │ HTTPS / 443
                      ▼
┌────────────────────────────────────────────────┐
│  云服务器（腾讯云 Lighthouse 4C4G 60GB）         │
│                                                │
│  ┌─────────────────┐    ┌────────────────────┐ │
│  │  Nginx (80/443) │───▶│ LANWatch (8000)    │ │
│  │  - SSL 终止      │    │ - FastAPI          │ │
│  │  - 反向代理      │    │ - SQLite 数据库    │ │
│  └─────────────────┘    └────────────────────┘ │
│                                                │
│  防火墙：22 + 80 + 443（8000 仅内网）            │
└────────────────────────────────────────────────┘
```

**核心特性**：
- ✅ HTTPS 加密（Let's Encrypt 自动续期）
- ✅ 多域名统一证书
- ✅ 隐私脱敏（无硬编码手机号、IP、微信二维码）
- ✅ 容器化部署（docker compose）
- ✅ 自动备份（SQLite 持久化卷）
- ✅ 健康检查（`/health` 端点）

---

## 1. 服务器准备

### 1.1 推荐规格

| 项目 | 推荐配置 | 最低 |
|---|---|---|
| 云厂商 | 腾讯云 Lighthouse / 阿里云 ECS | 任何云厂商 |
| CPU | 4 核 | 2 核 |
| 内存 | 4 GB | 2 GB |
| 系统盘 | 60 GB SSD | 40 GB |
| 公网带宽 | 5 Mbps | 3 Mbps |
| 操作系统 | Ubuntu 24.04 / 26.04 LTS | Ubuntu 22.04+ |

### 1.2 重装系统（干净部署）

**腾讯云 Lighthouse 控制台** → 实例 → 重装系统 → Ubuntu 24.04 LTS。

**注意**：腾讯云 CVM 和 Lighthouse 是两个独立产品，安全组/防火墙分开管理。
- CVM 在 https://console.cloud.tencent.com/cvm
- Lighthouse 在 https://console.cloud.tencent.com/lighthouse

### 1.3 验证基础环境

```bash
ssh root@<SERVER_IP> -i ~/.ssh/<key>
# 或者初始密码登录（重装后）

# 检查系统版本
cat /etc/os-release | head -3
# 应该是 Ubuntu 24.04 或 26.04
```

---

## 2. 域名与 DNS

### 2.1 推荐配置（至少 2 个域名）

| 用途 | 域名示例 |
|---|---|
| 主域 | `lanwatch.cn` |
| www 子域 | `www.lanwatch.cn` |
| 可选：备用域 | `lanwatch.net`, `www.lanwatch.net` |

### 2.2 在 DNSPod（或其他 DNS 服务商）添加 A 记录

| 主机记录 | 类型 | 记录值 |
|---|---|---|
| `@` | A | `<SERVER_IP>` |
| `www` | A | `<SERVER_IP>` |

### 2.3 验证 DNS 解析

```bash
nslookup lanwatch.cn
# 应该返回：Address: <SERVER_IP>
```

DNS 生效时间：通常 30 秒到 5 分钟。

---

## 3. SSH 密钥配置

### 3.1 本地生成专用部署密钥

```bash
# 在本地（Mac/Linux）
mkdir -p ~/.ssh/lanwatch_deploy
chmod 700 ~/.ssh/lanwatch_deploy
ssh-keygen -t ed25519 \
  -f ~/.ssh/lanwatch_deploy/id_ed25519 \
  -N "" \
  -C "lanwatch-deploy-$(date +%Y%m%d)"
```

**不设置密码**（由本地文件权限保护）。

### 3.2 上传公钥到服务器

**首次需要用密码登录**（重装系统时设置的密码）。任选一种：

**方式 A：用 ssh-copy-id**

```bash
ssh-copy-id -i ~/.ssh/lanwatch_deploy/id_ed25519.pub ubuntu@<SERVER_IP>
# 会提示输入 ubuntu 用户的密码
```

**方式 B：手动追加**

```bash
# 先获取公钥内容
cat ~/.ssh/lanwatch_deploy/id_ed25519.pub
# 复制输出（以 ssh-ed25519 AAAAC3... 开头）

# 在服务器上（用密码 SSH 进去）
ssh ubuntu@<SERVER_IP>
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo "<PASTE_PUBLIC_KEY_HERE>" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
exit
```

### 3.3 验证免密登录

```bash
ssh -i ~/.ssh/lanwatch_deploy/id_ed25519 ubuntu@<SERVER_IP> 'whoami && hostname'
# 应该输出 ubuntu 和 hostname，无需输入密码
```

> **Lighthouse 默认用户是 `ubuntu`**（不是 root）。该用户有 sudo 免密权限。

---

## 4. Docker 安装与镜像加速

### 4.1 安装 Docker + Docker Compose

```bash
ssh -i ~/.ssh/lanwatch_deploy/id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
echo "✓ Docker 安装完成"
docker --version
docker compose version
EOF
```

### 4.2 配置镜像加速（中国服务器必须）

不配置的话 docker build 慢（从 Docker Hub 拉镜像限速）。

```bash
ssh -i ~/.ssh/lanwatch_deploy/id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
sudo mkdir -p /etc/docker
cat << 'DAEMON_EOF' | sudo tee /etc/docker/daemon.json
{
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com",
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com"
  ]
}
DAEMON_EOF

sudo systemctl daemon-reload
sudo systemctl restart docker
sleep 3
sudo docker run --rm hello-world | tail -3
EOF
```

---

## 5. 代码部署

两种方式任选：

### 5.1 方式 A：从 GitHub clone（推荐）

```bash
ssh -i ~/.ssh/lanwatch_deploy/id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
cd /tmp
git clone --depth 1 https://github.com/cnchaoge/lanwatch_agent.git
sudo rm -rf /opt/lanwatch_agent
sudo mkdir -p /opt
sudo mv /tmp/lanwatch_agent /opt/lanwatch_agent
sudo chown -R ubuntu:ubuntu /opt/lanwatch_agent
cd /opt/lanwatch_agent
cp .env.example .env
echo "✓ 代码部署完成"
ls /opt/lanwatch_agent | head -10
EOF
```

### 5.2 方式 B：从本地 scp（GitHub 受限时）

```bash
# === 本地 Mac ===
cd /Users/chaoge/lanwatch_agent
tar czf /tmp/lanwatch_deploy.tar.gz \
  --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
  --exclude='monitor.db' --exclude='*.pyc' --exclude='.pytest_cache' \
  --exclude='agent/mac/build' --exclude='agent/mac/dist' \
  --exclude='.claude' --exclude='.DS_Store' \
  .

scp -i ~/.ssh/lanwatch_deploy/id_ed25519 \
  /tmp/lanwatch_deploy.tar.gz ubuntu@<SERVER_IP>:/tmp/

# === 服务器 ===
ssh -i ~/.ssh/lanwatch_deploy/id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
sudo mkdir -p /opt/lanwatch_agent
sudo tar xzf /tmp/lanwatch_deploy.tar.gz -C /opt/lanwatch_agent/
sudo chown -R ubuntu:ubuntu /opt/lanwatch_agent
cd /opt/lanwatch_agent
cp .env.example .env
# 清理 macOS 元数据
find . -name "._*" -type f -delete
echo "✓ scp 部署完成"
EOF
```

---

## 6. 环境变量配置（隐私脱敏）

> **重要原则**：以下字段**不要硬编码在代码里**，必须用环境变量。仓库代码已支持。

### 6.1 生成 .env 文件

```bash
ssh -i ~/.ssh/lanwatch_deploy/id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
cd /opt/lanwatch_agent
cp .env.example .env
echo "✓ .env 已生成"
EOF
```

### 6.2 编辑 .env（脱敏字段说明）

```bash
ssh -i ~/.ssh/lanwatch_deploy id_ed25519 ubuntu@<SERVER_IP> 'sudo nano /opt/lanwatch_agent/.env'
```

**必填字段**：

```bash
# === 必填 ===
ADMIN_PASSWORD=***  # 用命令生成：openssl rand -base64 18 | tr -d "/+=" | head -c 24
DB_PATH=/data/monitor.db
```

**可选字段（隐私脱敏）**：

```bash
# === 对外展示（脱敏）===
# 留空表示不显示该字段
CONTACT_PHONE=                 # 营销页显示的电话/微信
CONTACT_HOURS=工作时间          # 显示在电话旁边的工作时间
WECHAT_QR_URL=                 # 微信二维码的公网 URL（需要外部存储）
OFFICIAL_WEBSITE=https://github.com/cnchaoge/lanwatch_agent
SERVER_PUBLIC_URL=https://lanwatch.cn  # FAQ 中展示的服务端地址
```

**可选字段（LLM 配置，让 AI 数字分身能回答用户问题）**：

```bash
LLM_API_KEY=                  # 留空则 AI 数字分身不可用
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

**可选字段（报警）**：

```bash
SCKEY=                        # Server酱（微信报警）
DINGTALK_WEBHOOK=             # 钉钉机器人
FEISHU_WEBHOOK=               # 飞书机器人
```

**数据保留**：

```bash
RETENTION_PROBE_DAYS=5         # 探测日志保留天数
RETENTION_SNMP_DAYS=5
RETENTION_ALERT_DAYS=30
RETENTION_DIAG_DAYS=30
```

### 6.3 生成强密码（替换 ADMIN_PASSWORD）

```bash
# 在服务器上生成（不进聊天）
NEW_PASS=$(openssl rand -base64 18 | tr -d "/+=" | head -c 24)
echo "新密码已生成（长度 ${#NEW_PASS}）"

# 写到 .env
cd /opt/lanwatch_agent
sed -i "s|^ADMIN_PASSWORD=***" .env

# 备份密码到 root only 文件（找回用）
echo "${NEW_PASS}" | sudo tee /root/.lanwatch_admin_password > /dev/null
sudo chmod 600 /root/.lanwatch_admin_password

# 重建容器（让 .env 生效）
sudo docker compose up -d --force-recreate
sleep 8
curl -s http://localhost:8000/health
```

**找回密码**（SSH 到服务器后）：
```bash
sudo cat /root/.lanwatch_admin_password
```

---

## 7. Dockerfile 优化（中国服务器）

如果服务器在中国，`python:3.11-slim` 默认源 `deb.debian.org` 限速（~18 kB/s）。需要换成阿里云镜像。

编辑 `/opt/lanwatch_agent/Dockerfile`：

```dockerfile
FROM python:3.11-slim

# 替换默认 apt 源为阿里云镜像
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i "s|deb.debian.org|mirrors.aliyun.com|g" /etc/apt/sources.list.d/debian.sources; \
    fi

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    snmp net-tools iputils-ping traceroute \
    && rm -rf /var/lib/apt/lists/*

# pip 阿里云镜像加速
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get(\"http://localhost:8000/health\", timeout=5)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 8. 启动服务

```bash
ssh -i ~/.ssh/lanwatch_deploy/id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
cd /opt/lanwatch_agent

# 首次启动（构建 + 后台运行）
sudo docker compose up -d --build

# 验证容器运行
sudo docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 验证健康
sleep 10
curl -s http://localhost:8000/health
EOF
```

**预期输出**：

```
NAMES            STATUS                   PORTS
lanwatch-agent   Up 30 seconds (healthy)  0.0.0.0:8000->8000/tcp

{"status":"ok","db":"/data/monitor.db"}
```

---

## 9. Nginx 反向代理

### 9.1 安装 Nginx + Certbot

```bash
ssh -i ~/.ssh/lanwatch_deploy/id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
sudo apt install -y nginx certbot python3-certbot-nginx
sudo systemctl enable nginx
sudo systemctl start nginx
sudo rm -f /etc/nginx/sites-enabled/default
EOF
```

### 9.2 创建反向代理配置

```bash
ssh -i ~/.ssh/lanwatch_deploy/id_ed25519 ubuntu@<SERVER_IP> << 'NGINX_EOF'
sudo tee /etc/nginx/sites-available/lanwatch << 'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name lanwatch.cn www.lanwatch.cn lanwatch.net www.lanwatch.net;

    # 安全 headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    access_log /var/log/nginx/lanwatch.access.log;
    error_log /var/log/nginx/lanwatch.error.log;

    # 客户端请求体大小（agent 上报）
    client_max_body_size 10M;

    # 健康检查直返（不记日志）
    location = /health {
        proxy_pass http://127.0.0.1:8000/health;
        access_log off;
    }

    # 主反代
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;

        # WebSocket 支持（AI 数字分身聊天）
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # 超时
        proxy_connect_timeout 30s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/lanwatch /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
NGINX_EOF
```

### 9.3 验证 Nginx

```bash
curl -I http://lanwatch.cn/
# 期望：HTTP/1.1 200 OK 或 405 (HEAD 不被允许，GET 正常)
```

---

## 10. SSL 证书

### 10.1 申请证书（首张）

```bash
ssh -i ~/.ssh/lanwatch_deploy/id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
sudo certbot --nginx \
  -d lanwatch.cn -d www.lanwatch.cn \
  -d lanwatch.net -d www.lanwatch.net \
  --non-interactive --agree-tos --redirect \
  -m admin@lanwatch.cn
EOF
```

**效果**：
- 自动签发 Let's Encrypt 证书（90 天有效，自动续期）
- 自动配置 nginx 监听 443
- 自动 HTTP → HTTPS 301 重定向

### 10.2 扩展证书（增加新域名）

**场景**：已有证书，要加新域名。

```bash
ssh -i ~/.ssh/lanwatch_deploy id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
# 1. 在 nginx 配置的 server_name 加新域名
sudo sed -i "s|server_name lanwatch.cn www.lanwatch.cn lanwatch.net www.lanwatch.net;|server_name lanwatch.cn www.lanwatch.cn lanwatch.net www.lanwatch.net <NEW_DOMAIN>;|" /etc/nginx/sites-available/lanwatch

# 2. 扩展证书（--expand 不能少）
sudo certbot --nginx \
  -d lanwatch.cn -d www.lanwatch.cn \
  -d lanwatch.net -d www.lanwatch.net \
  -d <NEW_DOMAIN> \
  --expand --non-interactive --agree-tos --redirect \
  -m admin@lanwatch.cn

# 3. 如果上一步报"Could not install certificate"，手动安装
sudo certbot install --cert-name lanwatch.cn

# 4. 重载 nginx
sudo systemctl reload nginx
EOF
```

### 10.3 自动续期

certbot 自动配置 systemd timer：

```bash
systemctl list-timers | grep certbot
# 期望：Fri 2026-09-11 01:30:00 CST ... certbot.timer
```

手动测试续期（不会真的续期）：

```bash
sudo certbot renew --dry-run
```

### 10.4 查看证书信息

```bash
sudo certbot certificates
```

---

## 11. 腾讯云 Lighthouse 防火墙

在 [Lighthouse 控制台](https://console.cloud.tencent.com/lighthouse) → 实例 → 防火墙 → 添加规则：

| 协议 | 端口 | 来源 | 策略 | 备注 |
|---|---|---|---|---|
| TCP | 22 | 0.0.0.0/0 | 允许 | SSH |
| TCP | 80 | 0.0.0.0/0 | 允许 | HTTP（certbot 验证 + 自动跳转） |
| TCP | 443 | 0.0.0.0/0 | 允许 | HTTPS |
| TCP | 8000 | 0.0.0.0/0 | 允许 | **首次部署时** LANWatch 直连（**部署完成后删除**） |
| ICMP | - | 0.0.0.0/0 | 允许 | Ping（可选） |

**部署完成后建议删除 8000 规则**（nginx 已在 80/443 反代，8000 不应暴露公网）。

---

## 12. 端到端验证

### 12.1 服务层

```bash
ssh -i ~/.ssh/lanwatch_deploy id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
# 容器状态
sudo docker ps | grep lanwatch

# 健康检查
curl -s http://localhost:8000/health
# 期望：{"status":"ok","db":"/data/monitor.db"}

# 服务端日志（确认启动正常）
sudo docker logs lanwatch-agent --tail 10
EOF
```

### 12.2 营销页

```bash
# 通过 HTTPS GET
curl -L https://lanwatch.cn/ | grep -E "<title>|联系我们|访问 GitHub"

# 期望：
# <title>LANWatch - 企业网络监控平台</title>
#   <div class="section-eyebrow" style="color:var(--green);">联系我们</div>
#     <a class="btn btn-secondary" href="https://github.com/cnchaoge/lanwatch_agent">🌐 访问 GitHub 项目</a>
```

### 12.3 监控页

```bash
curl -I -L -X GET https://lanwatch.cn/enterprise/test
# 期望：HTTP/1.1 200 OK
```

### 12.4 隐私扫描（关键）

```bash
for d in lanwatch.cn www.lanwatch.cn lanwatch.net www.lanwatch.net; do
  echo "=== $d ==="
  curl -sL https://$d/ 2>&1 | grep -E "185-3172|18531729777|82\.156\.229\.67|lanwatch\.net\b" || echo "  ✓ 0 残留"
done
```

**期望全部 ✓ 0 残留**。

### 12.5 SSL 证书

```bash
echo | openssl s_client -servername lanwatch.cn -connect lanwatch.cn:443 2>/dev/null | openssl x509 -noout -subject -dates

# 期望：
# subject= /CN=lanwatch.cn
# notBefore=Sep 10 08:08:22 2026 GMT
# notAfter=Dec  9 08:08:21 2026 GMT
```

---

## 13. 常用运维命令

### 13.1 服务管理

```bash
# 容器状态
sudo docker ps | grep lanwatch

# 实时日志
sudo docker logs lanwatch-agent -f

# 最近 100 行日志
sudo docker logs lanwatch-agent --tail 100

# 重启容器（保留 .env 配置）
sudo docker compose restart lanwatch-agent

# 重建容器（修改 .env 后必须，否则 .env 不生效）
sudo docker compose up -d --force-recreate

# 停止
sudo docker compose down

# 完全清理（销毁容器和数据卷）
sudo docker compose down -v
sudo docker system prune -af  # 清理所有镜像
```

### 13.2 Nginx 管理

```bash
# 配置测试
sudo nginx -t

# 重载
sudo systemctl reload nginx

# 重启
sudo systemctl restart nginx

# 错误日志
sudo tail -f /var/log/nginx/lanwatch.error.log

# 访问日志
sudo tail -f /var/log/nginx/lanwatch.access.log
```

### 13.3 SSL 证书管理

```bash
# 查看所有证书
sudo certbot certificates

# 测试续期（不会真续期）
sudo certbot renew --dry-run

# 强制续期
sudo certbot renew --force-renewal

# 撤销证书
sudo certbot revoke --cert-path /etc/letsencrypt/live/lanwatch.cn/fullchain.pem
```

---

## 14. 数据备份与恢复

### 14.1 数据库备份（核心）

```bash
# 备份到 /backup 目录
ssh -i ~/.ssh/lanwatch_deploy id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
sudo mkdir -p /backup
sudo cp /opt/lanwatch_agent/data/monitor.db \
        /backup/lanwatch_$(date +%Y%m%d_%H%M%S).db
sudo ls -lh /backup/
EOF
```

### 14.2 配置备份

```bash
ssh -i ~/.ssh/lanwatch_deploy id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
sudo cp /opt/lanwatch_agent/.env /backup/env_$(date +%Y%m%d)
sudo cp /etc/nginx/sites-available/lanwatch /backup/nginx_lanwatch_$(date +%Y%m%d)
echo "✓ 配置已备份"
EOF
```

### 14.3 自动备份（cron）

```bash
# 每天凌晨 3 点自动备份
ssh -i ~/.ssh/lanwatch_deploy id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
cat << 'CRON_EOF' | sudo tee /etc/cron.d/lanwatch-backup
0 3 * * * root cp /opt/lanwatch_agent/data/monitor.db /backup/lanwatch_$(date +\%Y\%m\%d).db && find /backup -name "lanwatch_*.db" -mtime +30 -delete
CRON_EOF

sudo systemctl restart cron
EOF
```

### 14.4 恢复数据库

```bash
ssh -i ~/.ssh/lanwatch_deploy id_ed25519 ubuntu@<SERVER_IP> << 'EOF'
# 1. 停止服务
sudo docker compose down

# 2. 恢复数据库
sudo cp /backup/lanwatch_<DATE>.db /opt/lanwatch_agent/data/monitor.db
sudo chown -R ubuntu:ubuntu /opt/lanwatch_agent/data

# 3. 重启服务
sudo docker compose up -d
EOF
```

---

## 15. 故障排查

### 15.1 容器起不来

```bash
# 查看容器日志
sudo docker logs lanwatch-agent --tail 50

# 检查 .env 格式（每行 KEY=VALUE，无引号）
cat /opt/lanwatch_agent/.env

# 检查端口占用
sudo ss -tlnp | grep 8000

# 手动启动容器调试
sudo docker run -it --rm \
  -p 8000:8000 \
  --env-file /opt/lanwatch_agent/.env \
  -v /opt/lanwatch_agent/data:/data \
  lanwatch-agent
```

### 15.2 HTTPS 不通

**症状**：浏览器 `https://lanwatch.cn/` 打不开，显示连接被拒绝。

```bash
# 1. 检查 Lighthouse 防火墙 80/443 端口是否放通
# （在 https://console.cloud.tencent.com/lighthouse 配置）

# 2. 检查 DNS 解析
nslookup lanwatch.cn

# 3. 检查 nginx 配置
sudo nginx -t

# 4. 检查证书
sudo certbot certificates

# 5. 检查端口监听
sudo ss -tlnp | grep -E ":80|:443"
```

### 15.3 502 Bad Gateway

**症状**：浏览器看到 nginx 502 错误。

```bash
# 容器没运行
sudo docker ps | grep lanwatch
# 如果没运行：
sudo docker compose up -d

# 容器在运行但服务没启动
sudo docker logs lanwatch-agent --tail 30
```

### 15.4 内存 / CPU 占用过高

```bash
# 查看资源占用
sudo docker stats lanwatch-agent

# 如果是 Python 内存泄漏，重启容器
sudo docker compose restart lanwatch-agent

# 清理日志
sudo sh -c 'sudo docker logs lanwatch-agent 2>&1 > /tmp/last.log; truncate -s 0 /var/lib/docker/containers/$(sudo docker inspect --format="{{.Id}}" lanwatch-agent)/*-json.log'
```

### 15.5 Docker build 极慢（> 30 分钟）

**原因**：Docker Hub 限速或 Dockerfile 没换阿里云镜像。

```bash
# 1. 确认镜像加速配置
cat /etc/docker/daemon.json

# 2. 检查 Dockerfile 是否优化（中国服务器）
head -10 /opt/lanwatch_agent/Dockerfile
# 应该看到 mirrors.aliyun.com

# 3. 如果 Dockerfile 没优化，按本文档第 7 节修改
```

### 15.6 证书自动续期失败

```bash
# 手动测试续期
sudo certbot renew --dry-run

# 查看 certbot 日志
sudo tail -f /var/log/letsencrypt/letsencrypt.log

# 常见原因：
# - 80 端口被防火墙挡住（certbot 用 HTTP 验证）
# - DNS 解析失败
# - nginx 配置错误
```

### 15.7 找回 admin 密码

```bash
# 通过 SSH 找回
ssh -i ~/.ssh/lanwatch_deploy ubuntu@<SERVER_IP>
sudo cat /root/.lanwatch_admin_password
```

### 15.8 容器内 Python 调试

```bash
# 进入容器
sudo docker exec -it lanwatch-agent bash

# 查看容器内环境变量
env | grep -E "ADMIN|CONTACT|LLM"

# 测试 Python
python3 -c "from core.config import config; print(config.ADMIN_PASSWORD[:4] + '***')"

# 测试 API
curl http://localhost:8000/health
```

---

## 附录 A：完整部署时间参考

| 阶段 | 耗时 |
|---|---|
| 服务器重装 | 5 分钟 |
| SSH 密钥配置 | 5 分钟 |
| Docker 安装 + 镜像加速 | 5 分钟 |
| 代码部署（GitHub clone） | 5 分钟 |
| 首次 docker build（含 apt + pip 下载） | 25 分钟（限速环境） |
| Nginx 反代 + SSL 证书 | 10 分钟 |
| 腾讯云防火墙 | 5 分钟 |
| **总计** | **约 1 小时** |

## 附录 B：相关链接

- GitHub: https://github.com/cnchaoge/lanwatch_agent
- Let's Encrypt: https://letsencrypt.org/
- Certbot: https://certbot.eff.org/
- 腾讯云 Lighthouse: https://console.cloud.tencent.com/lighthouse
- DNSPod: https://console.cloud.tencent.com/cns

---

**最后更新**：2026-09-10
**适用版本**：Lanwatch v1.0.0+
