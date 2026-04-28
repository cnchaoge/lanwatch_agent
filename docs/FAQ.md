# 常见问题

## Q: 服务启动报错 ModuleNotFoundError

确保在 `server/` 目录下运行，并安装了所有依赖：

```bash
pip install -r requirements.txt
```

## Q: 告警收不到

1. 确认 `SCKEY` / `DINGTALK_WEBHOOK` / `FEISHU_WEBHOOK` 环境变量已设置
2. 测试告警渠道：`POST /api/alerts/test?channel=serverchan`
3. 检查告警冷却期（同一告警 5 分钟内不重复推送）

## Q: SNMP 设备添加失败

1. 确认目标设备支持 SNMP 并配置了 community（默认 public）
2. 确认网络可达：`ping <目标IP>`
3. 手动测试：`snmpwalk -v 2c -c public <目标IP> 1.3.6.1.2.1.1.1.0`

## Q: 拓扑发现没有结果

1. 种子 IP 必须是 SNMP 设备
2. 目标设备需开启 LLDP 或 CDP
3. 检查 SNMP community 是否正确

## Q: 钉钉/飞书 Webhook 如何获取？

- 钉钉：群设置 → 智能群助手 → 添加机器人 → 选择「自定义」→ 复制 Webhook URL
- 飞书：群设置 → 群机器人 → 添加机器人 → 复制 Webhook URL

## Q: 如何修改探测间隔？

1. Web UI：设备详情 → 编辑
2. API：`POST /api/scheduler/job?agent_id=xxx&probe_type=ping&target=8.8.8.8&interval_seconds=120`

## Q: 数据库在哪里？

默认在 `server/monitor.db`（SQLite）。如需迁移：

```bash
# 备份
cp monitor.db monitor.db.bak

# 指定路径
export DATABASE_URL=/path/to/monitor.db
```
