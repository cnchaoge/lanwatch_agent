# 软路由器客户端

支持 OpenWRT、iKuai、LEDE、蒲公英等基于 Linux 的软路由系统。

## 目标系统

- **OpenWRT**（主流软路由固件，opkg 包管理）
- **iKuai**（流控路由，官方定制 Linux）
- **LEDE**（OpenWRT 分支，兼容）
- **蒲公英**（贝锐出品，基于 OpenWRT 定制）
- **爱快 (iKuai)**（软路由流控系统）

## 技术方案

软路由 Agent 以 **OpenWRT LuCI CGI** 或 **自定义 uhttpd API** 方式部署，
运行在路由器本地，24 小时在线，不占用客户电脑。

典型架构：
```
路由器 (OpenWRT)  ── 本地 Agent ──▶  云端服务端 (82.156.229.67)
                │
                └── 每 60s 上报监控数据
                └── 拓扑扫描 / SNMP 查询
```

## 状态

🛠 开发中 — 待实现
