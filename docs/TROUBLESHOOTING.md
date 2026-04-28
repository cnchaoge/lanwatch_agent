# 故障排查

## 服务无法启动

### 检查端口占用

```bash
# Linux
lsof -i :8000

# Windows
netstat -ano | findstr :8000
```

### 检查 Python 版本

```bash
python --version  # 需要 3.9+
```

### 查看日志

服务启动时会输出日志到 stdout，错误信息会显示具体原因。

## Agent 无法注册

1. 确认服务端运行中：`curl http://localhost:8000/health`
2. 检查网络连通性：`curl http://your-server:8000/api/register`
3. 确认 `config.json` 中的 `api_base` 填写正确
4. 查看 agent 日志中的错误信息

## 探测超时

- 默认超时：ping 4 秒，traceroute 30 秒，portscan 3 秒
- 调整方法：修改 `server/core/config.py` 中的超时参数
- Windows ping 使用 `-w` 参数（毫秒）
- Linux/macOS ping 使用 `-W` 参数（秒）

## 数据库损坏

如 SQLite 数据库损坏（极少发生）：

```bash
# 备份
cp monitor.db monitor.db.bak

# 修复
sqlite3 monitor.db ".recover" | sqlite3 monitor.db.new
mv monitor.db.new monitor.db
```
