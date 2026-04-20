-- LuCI CBI Model for lanwatch configuration
require("luci.sys")
require("luci.util")

local m = Map("lanwatch", "LanWatch 网络监控",
    [[软路由监控客户端，监控网络状态并上报至云端服务器。]])

local s = m:section(NamedSection, "agent", "lanwatch", "基本设置")
s.addremove = false
s.anonymous = true

local e = s:option(Flag, "enabled", "启用",
    "开启后自动启动监控客户端")
e.default = "0"
e.rmempty = false

local o = s:option(Value, "server_url", "服务端地址",
    "云端服务器地址，默认为 http://82.156.229.67:8000")
o.default = "http://82.156.229.67:8000"
o.datatype = "string"

local interval = s:option(Value, "interval", "上报间隔",
    "单位秒，默认60秒")
interval.default = "60"
interval.datatype = "uinteger"

local target = s:option(Value, "target_host", "监控目标",
    "留空则监控网关，也可填ERP服务器IP或域名")
target.datatype = "string"
target.placeholder = "留空监控网关"

-- 状态查看 section
local status = m:section(TypedSection, "status", "运行状态")
status.anonymous = true

local running = status:option(DummyValue, "_running", "运行状态")
function running.cfgvalue(self, section)
    local pid = luci.sys.exec("cat /var/run/lanwatch.pid 2>/dev/null")
    if pid and #pid > 0 then
        local ok = os.execute("kill -0 " .. pid .. " 2>/dev/null")
        if ok == 0 or ok == true then
            return "运行中 (PID: " .. pid .. ")"
        end
    end
    return "未运行"
end

local agent_id = status:option(DummyValue, "_agent_id", "Agent ID")
function agent_id.cfgvalue(self, section)
    local cfg = "/etc/lanwatch/agent.json"
    local f = io.open(cfg, "r")
    if f then
        local content = f:read("*all")
        f:close()
        local c = luci.json.decode(content)
        return c and c.agent_id or "未注册"
    end
    return "未注册"
end

local log_btn = status:option(Button, "_log", "查看日志")
log_btn.inputtitle = "查看日志"
log_btn.inputstyle = "button"
function log_btn.cfgvalue(self, section)
    return "查看日志"
end

return m
