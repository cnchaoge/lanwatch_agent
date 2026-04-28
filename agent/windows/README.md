# Windows Agent

Lanwatch Agent for Windows，支持注册为 Windows Service 运行。

## 安装

### 前置条件

- Python 3.8+
- Windows 7+

### 安装步骤

```powershell
cd agent/windows
pip install -r requirements.txt
```

### 注册为 Windows Service（需要管理员权限）

```powershell
python setup.py install
```

### 启动服务

```powershell
net start LanwatchAgent
```

### 查看状态

```powershell
python main.py --status
```

## 配置文件

编辑 `config.json`：

```json
{
  "api_base": "http://your-server:8000",
  "agent_id": "windows-pc-001",
  "interval": 60,
  "token": ""
}
```

## 卸载

```powershell
python setup.py remove
net stop LanwatchAgent
```

## 开发测试

### 前台运行（不安装 Service）

```powershell
python main.py
```

## 构建安装包

```powershell
pip install pyinstaller
pyinstaller lanwatch_agent.spec --onefile
```

输出：`dist/lanwatch_agent.exe`
