# ADB Proxy Server

一个高性能的 ADB 代理服务器，支持远程 Android 设备调试和 scrcpy 屏幕镜像。通过 TCP 代理实现跨网络的 ADB 连接和 scrcpy 流媒体传输。

## 功能特性

- 🔄 **ADB 协议代理**: 完整支持 ADB 协议，实现远程设备调试
- 📱 **Scrcpy 集成**: 自动启动和管理 scrcpy 服务器，支持屏幕镜像
- 🌐 **多设备支持**: 同时代理多个 Android 设备
- 🚀 **高性能异步**: 基于 asyncio 的高并发处理
- 🔧 **自动化管理**: 自动检测设备并分配端口

## 系统要求

- Python 3.7+
- ADB (Android Debug Bridge)
- 网络连接的 Android 设备

## 安装

### 1. 克隆项目
```bash
git clone <repository-url>
cd adb-reverse-proxy
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 确保 ADB 可用
```bash
adb version
```

## 快速开始

### 服务端操作流程

#### 1. 连接 Android 设备
```bash
# USB 连接
adb devices

# 或 WiFi 连接
adb connect <device-ip>:5555
```

#### 2. 启动代理服务器
```bash
cd adbproxy
python server.py
```

服务器启动后会显示：
```
Found 1 device(s)

=== ADB Proxy Ports ===
Device: 6DUKU479EYNB6XZL
  ADB Port: 6000 (adb connect <server_ip>:6000)
  Scrcpy Port: 7000 (for scrcpy TCP streams)

=== Usage Instructions ===
1. Connect ADB: adb connect <server_ip>:<adb_port>
2. Run scrcpy with TCP tunnel: scrcpy --tunnel-host=<server_ip> --tunnel-port=<scrcpy_port>
   Note: The proxy will automatically start the scrcpy server on the device

Proxy servers started. Press Ctrl+C to stop.
```

### 客户端操作流程

#### 方式一：ADB 调试

1. **连接到代理服务器**
```bash
adb connect <server_ip>:6000
```

2. **验证连接**
```bash
adb devices
```

3. **使用 ADB 命令**
```bash
# 安装应用
adb install app.apk

# 查看日志
adb logcat

# 进入 shell
adb shell

# 文件传输
adb push local_file /sdcard/
adb pull /sdcard/remote_file .
```

#### 方式二：Scrcpy 屏幕镜像

1. **启动 scrcpy**
```bash
scrcpy --tunnel-host=<server_ip> --tunnel-port=7000
```

2. **高级选项**
```bash
# 指定分辨率
scrcpy --tunnel-host=<server_ip> --tunnel-port=7000 --max-size=1024

# 指定比特率
scrcpy --tunnel-host=<server_ip> --tunnel-port=7000 --bit-rate=2M

# 录制屏幕
scrcpy --tunnel-host=<server_ip> --tunnel-port=7000 --record=recording.mp4
```

## 多台机器场景使用指南

### 场景一：多个客户端连接同一服务器

```
┌─────────────┐    ┌─────────────────┐    ┌─────────────┐
│  客户端 A   │────│   代理服务器    │────│ Android 设备│
└─────────────┘    │   (server.py)   │    └─────────────┘
┌─────────────┐    │                 │
│  客户端 B   │────│  端口分配：     │
└─────────────┘    │  ADB: 6000      │
┌─────────────┐    │  Scrcpy: 7000   │
│  客户端 C   │────│                 │
└─────────────┘    └─────────────────┘
```

**配置步骤：**

1. **服务器端**（运行 Android 设备的机器）
```bash
# 启动代理服务器
python server.py
```

2. **客户端 A、B、C**
```bash
# 每个客户端都可以独立连接
adb connect <server_ip>:6000
scrcpy --tunnel-host=<server_ip> --tunnel-port=7000
```

### 场景二：多个 Android 设备分布在不同服务器

```
┌─────────────┐    ┌─────────────────┐    ┌─────────────┐
│             │────│   服务器 A      │────│  设备 A     │
│             │    │   端口: 6000/7000│    └─────────────┘
│   客户端    │    └─────────────────┘
│             │    ┌─────────────────┐    ┌─────────────┐
│             │────│   服务器 B      │────│  设备 B     │
└─────────────┘    │   端口: 6000/7000│    └─────────────┘
                   └─────────────────┘
```

**配置步骤：**

1. **服务器 A**
```bash
python server.py  # 设备 A 在端口 6000/7000
```

2. **服务器 B**
```bash
python server.py  # 设备 B 在端口 6000/7000
```

3. **客户端操作**
```bash
# 连接设备 A
adb connect <server_a_ip>:6000
scrcpy --tunnel-host=<server_a_ip> --tunnel-port=7000

# 连接设备 B
adb connect <server_b_ip>:6000
scrcpy --tunnel-host=<server_b_ip> --tunnel-port=7000

# 查看所有连接的设备
adb devices
```

### 场景三：单服务器多设备

```
┌─────────────┐    ┌─────────────────┐    ┌─────────────┐
│             │    │                 │────│  设备 A     │
│   客户端    │────│   代理服务器    │    └─────────────┘
│             │    │                 │    ┌─────────────┐
└─────────────┘    │  设备 A: 6000/7000│────│  设备 B     │
                   │  设备 B: 6001/7001│    └─────────────┘
                   └─────────────────┘
```

**配置步骤：**

1. **连接多个设备到服务器**
```bash
# 连接设备 A
adb connect <device_a_ip>:5555

# 连接设备 B  
adb connect <device_b_ip>:5555

# 验证连接
adb devices
```

2. **启动代理服务器**
```bash
python server.py
```

输出示例：
```
Found 2 device(s)

=== ADB Proxy Ports ===
Device: DEVICE_A_ID
  ADB Port: 6000
  Scrcpy Port: 7000

Device: DEVICE_B_ID
  ADB Port: 6001
  Scrcpy Port: 7001
```

3. **客户端连接**
```bash
# 连接设备 A
adb connect <server_ip>:6000
scrcpy --tunnel-host=<server_ip> --tunnel-port=7000

# 连接设备 B
adb connect <server_ip>:6001
scrcpy --tunnel-host=<server_ip> --tunnel-port=7001
```

## 端口分配规则

- **ADB 端口**: 从 6000 开始，每个设备递增 1
- **Scrcpy 端口**: 从 7000 开始，每个设备递增 1
- **设备索引**: 按照 `adb devices` 的顺序分配

## 网络配置

### 防火墙设置

确保以下端口在服务器上开放：

```bash
# Ubuntu/Debian
sudo ufw allow 6000:6010/tcp
sudo ufw allow 7000:7010/tcp

# CentOS/RHEL
sudo firewall-cmd --permanent --add-port=6000-6010/tcp
sudo firewall-cmd --permanent --add-port=7000-7010/tcp
sudo firewall-cmd --reload
```

### 网络测试

```bash
# 测试 ADB 端口连通性
telnet <server_ip> 6000

# 测试 Scrcpy 端口连通性
telnet <server_ip> 7000
```

## 故障排除

### 常见问题

1. **Connection refused**
   - 检查防火墙设置
   - 确认服务器正在运行
   - 验证端口号正确

2. **设备未找到**
   - 确认设备已连接到服务器
   - 检查 USB 调试是否开启
   - 验证 ADB 连接状态

3. **Scrcpy 连接失败**
   - 等待服务器自动启动 scrcpy-server
   - 检查设备权限设置
   - 确认网络延迟不会太高

### 调试模式

启用详细日志：

```bash
# 查看实时日志
tail -f adbproxy/scrcpy.log

# 修改日志级别（在 server.py 中）
logging.basicConfig(level=logging.DEBUG)
```

## 性能优化

### 网络优化

```bash
# Scrcpy 性能调优
scrcpy --tunnel-host=<server_ip> --tunnel-port=7000 \
       --max-size=1024 \
       --bit-rate=2M \
       --max-fps=30
```

### 服务器优化

- 使用 SSD 存储提高 I/O 性能
- 确保充足的网络带宽
- 监控 CPU 和内存使用情况

## 安全注意事项

- 仅在受信任的网络环境中使用
- 考虑使用 VPN 进行远程连接
- 定期更新 ADB 和相关工具
- 限制代理服务器的网络访问权限

## 许可证

本项目采用 MIT 许可证。详见 LICENSE 文件。

## 贡献

欢迎提交 Issue 和 Pull Request 来改进项目。

## 更新日志

### v1.0.0
- 初始版本发布
- 支持 ADB 协议代理
- 集成 Scrcpy 自动启动
- 多设备支持
