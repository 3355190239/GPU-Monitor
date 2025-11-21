# GPU Monitor (Agentless SSH 版)

> **服务器集群监控面板 / 课题组显卡状态看板 / 轻量级 GPU 监控系统**
>
> **A lightweight, agentless GPU cluster monitoring dashboard for Labs & Servers.**

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-green)
![BasedOn](https://img.shields.io/badge/based%20on-gpuview-orange)

## 📸 截图预览

<img width="1872" height="924" alt="image" src="https://github.com/user-attachments/assets/35c8db4a-afbb-4219-b486-a4277c3d365e" />

<img width="1872" height="924" alt="image" src="https://github.com/user-attachments/assets/0645425f-8deb-426c-9277-ee321c39688c" />

## 📖 项目简介 (Introduction)

这是一个基于 Python + Flask 开发的**轻量级 GPU 集群监控面板**。

它专为**深度学习课题组、实验室或小型服务器集群**设计。与传统的监控工具（如 Prometheus + Grafana）不同，本项目采用**无 Agent (Agentless)** 模式：
你**无需**在被监控的 GPU 服务器上安装任何软件或 Python 包，只需要在主控机上配置 SSH 信息，即可通过 SSH 协议直连采集数据。

## 💡 致敬与改编说明 (Credits & Modifications)

本项目基于 **[fgaim/gpuview](https://github.com/fgaim/gpuview)** 进行深度二次开发。感谢原作者提供了优秀的 UI 概念。

**本项目的主要改动 (Key Modifications):**

1.  **架构重构 (Architecture Change)**:
    *   **原版**: 采用 Agent 模式，需要在**每一台**显卡机器上部署服务。
    *   **本版**: **SSH 直连模式**！仅需在监控端运行，被监控端无需任何配置，只要能 SSH 连上且有显卡驱动即可。

2.  **后端优化 (Backend Optimization)**:
    *   实现 **SSH 连接池** 与 Keep-Alive，防止高并发下连接断开。
    *   引入 **后台线程轮询**，API 毫秒级响应，不再因为网络延迟卡顿。
    *   合并 SSH 指令，大幅减少网络开销。

3.  **前端重制 (Frontend Overhaul)**:
    *   升级至 **Bootstrap 5**，全深色模式 (Dark Mode)。
    *   **局部 Diff 更新**：解决原版页面闪烁问题，数字跳动更平滑。
    *   **信息布局优化**：分离服务器名称与 IP，支持显示显卡占用进程和用户名。

---

## ✨ 功能特点

*   **零侵入 (Agentless)**：被监控节点只需开启 SSH，无需安装任何依赖。
*   **课题组友好**：
    *   支持给 IP 起别名（如：`[王师兄的4090]`），一目了然。
    *   **显示占用者**：直观看到是谁（用户名）在使用显卡，方便协调资源。
*   **实时监控**：每 3 秒自动刷新，支持暂停/继续。
*   **多维数据**：温度、显存、利用率、功耗、进程详情。

## 🛠️ 安装与使用

### 1. 克隆项目与安装依赖

```bash
git clone https://github.com/3355190239/GPU-Monitor/gpu-monitor.git
cd gpu-monitor

# 推荐使用虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 安装依赖
pip install flask paramiko
```

### 2. 配置服务器列表 (`config.ini`)

在根目录新建 `config.ini`。
**技巧**：`[]` 里的名字会直接显示在网页卡片标题上，支持中文。

```ini
[server1]
hostname = 192.168.1.100
port = 22
username = root
password = your_password

[server2]
hostname = 192.168.1.101
port = 22
username = zhangsan
password = secret_password
```

### 3. 启动服务

```bash
python app.py
```

启动后，访问浏览器：[http://localhost:8888](http://localhost:8888)

---

## ⚙️ 部署为后台服务 (Linux Systemd)

为了让监控面板在服务器重启后自动运行，建议配置 Systemd。

1. 创建服务文件：`sudo nano /etc/systemd/system/gpu-monitor.service`

2. 写入内容（请修改路径）：

```ini
[Unit]
Description=GPU Monitor Dashboard
After=network.target

[Service]
Type=simple
User=root
# 修改为项目所在目录
WorkingDirectory=/home/admin/gpu-monitor
# 修改为虚拟环境的 python 路径
ExecStart=/home/admin/gpu-monitor/venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

3. 启动并开机自启：

```bash
sudo systemctl daemon-reload
sudo systemctl enable gpu-monitor
sudo systemctl start gpu-monitor
```




## 📄 许可证

本项目遵循 [MIT License](LICENSE) 开源协议。
