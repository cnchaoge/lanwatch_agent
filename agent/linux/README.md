# Linux Agent

Lanwatch Agent for Linux，支持注册为 systemd 服务。

## 安装

```bash
cd agent/linux
pip install -r requirements.txt
```

### 注册 systemd 服务

```bash
sudo cp lanwatch_agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable lanwatch_agent
sudo systemctl start lanwatch_agent
```

### 查看状态

```bash
sudo systemctl status lanwatch_agent
```

## 配置

编辑 `/etc/lanwatch/agent.json`：

```json
{
  "api_base": "http://your-server:8000",
  "agent_id": "linux-server-001",
  "interval": 60,
  "token": ""
}
```

## 卸载

```bash
sudo systemctl stop lanwatch_agent
sudo systemctl disable lanwatch_agent
sudo rm /etc/systemd/system/lanwatch_agent.service
sudo rm -rf /etc/lanwatch
```
