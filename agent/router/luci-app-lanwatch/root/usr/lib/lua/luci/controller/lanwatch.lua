-- LuCI Controller for lanwatch
module("luci.controller.lanwatch", package.seeall)

function index()
    entry({"admin", "services", "lanwatch"},
        cbi("lanwatch"),
        "LanWatch 网络监控",
        30)

    entry({"admin", "services", "lanwatch", "status"},
        call("action_status"),
        "状态",
        1)
end

function action_status()
    local json = require("luci.json")
    local fs = require("nixio.fs")

    local status = {
        running = false,
        agent_id = "",
        version = "0.5.0",
        log = ""
    }

    -- 检查 agent 是否在运行
    local pid = fs.readfile("/var/run/lanwatch.pid")
    if pid and tonumber(pid) then
        local ok = os.execute("kill -0 " .. pid .. " 2>/dev/null")
        status.running = (ok == true or ok == 0)
    end

    -- 读取配置
    local cfg = "/etc/lanwatch/agent.json"
    if fs.access(cfg) then
        local f = io.open(cfg, "r")
        if f then
            local content = f:read("*all")
            f:close()
            local c = json.decode(content)
            if c then
                status.agent_id = c.agent_id or ""
            end
        end
    end

    -- 读取日志（最后20行）
    local log = "/tmp/lanwatch_agent.log"
    if fs.access(log) then
        local f = io.popen("tail -n 20 " .. log)
        if f then
            status.log = f:read("*all")
            f:close()
        end
    end

    luci.http.prepare_content("application/json")
    luci.http.write_json(status)
end
