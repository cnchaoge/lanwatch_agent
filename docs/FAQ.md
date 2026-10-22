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
