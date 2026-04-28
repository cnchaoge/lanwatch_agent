# API 参考

## 设备注册

```
POST /api/register
```

Body: `{ "agent_id": "...", "hostname": "...", "platform": "windows|linux|router" }`

Response: `{ "success": true, "agent_id": "...", "agent_token": "..." }`

## 探测上报

```
POST /api/{agent_id}/report          Bearer Token
POST /api/{agent_id}/topology        Bearer Token
POST /api/{agent_id}/diag            Bearer Token
```

## 主动探测

```
GET  /api/probe/ping?host=&count=&timeout=
GET  /api/probe/traceroute?host=&max_hops=
GET  /api/probe/portscan?host=&ports=
GET  /api/probe/dns?domain=&servers=
GET  /api/probe/http?url=&timeout=
```

## 调度管理

```
POST /api/scheduler/job
DELETE /api/scheduler/job
GET  /api/scheduler/jobs
POST /api/scheduler/job/{id}/run
GET  /api/scheduler/rules
POST /api/scheduler/reload
```

## SNMP 设备

```
POST /api/snmp/devices
DELETE /api/snmp/devices/{agent_id}/{ip}
GET  /api/snmp/devices/{agent_id}
POST /api/snmp/collect/{agent_id}/{ip}
POST /api/snmp/collect_all
```

## 拓扑管理

```
POST /api/topology/discover
GET  /api/topology
GET  /api/topology/nodes
GET  /api/topology/links
GET  /api/topology/node/{ip}
DELETE /api/topology/node/{ip}
GET  /api/topology/stats
```

## 告警管理

```
GET  /api/alerts
GET  /api/alerts/stats
POST /api/alerts/{id}/ack
DELETE /api/alerts/clear
GET  /api/alerts/channels
POST /api/alerts/channels
GET  /api/alerts/rules
POST /api/alerts/test
```

## 历史数据

```
GET  /api/history/probe_results
GET  /api/history/trends/ping?target=&hours=
GET  /api/history/device_status
GET  /api/history/snmp_metrics?device_ip=&hours=
```

## 诊断

```
POST /api/diagnosis/diagnose
POST /api/diagnosis/diagnose_from_history
GET  /api/diagnosis/rules
GET  /api/diagnosis/quick/{agent_id}
```

## 排查向导

```
GET  /api/wizard/scenarios
POST /api/wizard/start?scenario_id=
POST /api/wizard/{session_id}/answer
GET  /api/wizard/{session_id}/status
```

## 故障传播

```
GET  /api/propagation/chain/{ip}
POST /api/propagation/root_cause
GET  /api/propagation/correlate
GET  /api/propagation/topology_impact/{ip}
```
