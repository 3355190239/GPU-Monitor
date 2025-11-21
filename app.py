import configparser
import time
import threading
import paramiko
from flask import Flask, render_template, jsonify
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# ================= 配置与全局变量 =================
# 读取配置 (只在启动时读取一次)
config = configparser.ConfigParser()
try:
    config.read('config.ini')
    SERVERS = [dict(config.items(s)) for s in config.sections()]
except Exception as e:
    print(f"Error reading config.ini: {e}")
    SERVERS = []

# SSH 连接池
SSH_CLIENTS = {}
SSH_LOCK = threading.Lock()

# 全局数据缓存 (API 直接读这里，不等待 SSH)
GLOBAL_GPU_STATS = []
CACHE_LOCK = threading.Lock()

# ================= 命令定义 =================
# 将两个 nvidia-smi 命令用分号连接，中间用 echo 打印分隔符
# 这样一次 SSH 就能拿回 GPU 状态和 进程状态
SEPARATOR = "|||SECTION_SPLIT|||"

NVIDIA_SMI_GPU_FIELDS = (
    'uuid', 'index', 'name', 'temperature.gpu', 'utilization.gpu',
    'memory.used', 'memory.total', 'power.draw', 'power.limit'
)
CMD_GPU = f'nvidia-smi --query-gpu={",".join(NVIDIA_SMI_GPU_FIELDS)} --format=csv,noheader,nounits'

NVIDIA_SMI_PROC_FIELDS = ('gpu_uuid', 'pid', 'process_name', 'used_gpu_memory')
CMD_PROC = f'nvidia-smi --query-compute-apps={",".join(NVIDIA_SMI_PROC_FIELDS)} --format=csv,noheader,nounits'

# 合并后的命令
COMBINED_CMD = f"{CMD_GPU} ; echo '{SEPARATOR}' ; {CMD_PROC}"


# ================= 核心逻辑 =================

def get_ssh_client(host_details):
    """获取或创建带有 Keep-Alive 的 SSH 连接"""
    hostname = host_details['hostname']
    with SSH_LOCK:
        client = SSH_CLIENTS.get(hostname)
        if client and client.get_transport() and client.get_transport().is_active():
            return client

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname,
                port=int(host_details['port']),
                username=host_details['username'],
                password=host_details['password'],
                timeout=5,
                banner_timeout=5
            )
            # 开启 KeepAlive，每30秒发送一次心跳，防止连接断开
            client.get_transport().set_keepalive(30)
            SSH_CLIENTS[hostname] = client
            return client
        except Exception as e:
            # 如果连接失败，清理旧连接
            SSH_CLIENTS.pop(hostname, None)
            raise e


def fetch_single_server_data(host_details):
    """采集单台服务器数据"""
    hostname = host_details['hostname']
    try:
        client = get_ssh_client(host_details)

        # 1. 执行合并后的 nvidia-smi 命令
        stdin, stdout, stderr = client.exec_command(COMBINED_CMD, timeout=10)
        output = stdout.read().decode('utf-8').strip()

        if not output:
            return {"hostname": hostname, "error": "Empty response from nvidia-smi"}

        # 解析输出，通过分隔符拆分两部分数据
        parts = output.split(SEPARATOR)
        gpu_lines = parts[0].strip().splitlines() if len(parts) > 0 else []
        proc_lines = parts[1].strip().splitlines() if len(parts) > 1 else []

        # 解析 GPU 基础信息
        gpus = []
        for line in gpu_lines:
            if not line.strip(): continue
            vals = [v.strip() for v in line.split(',')]
            if len(vals) < len(NVIDIA_SMI_GPU_FIELDS): continue
            gpus.append(dict(zip(NVIDIA_SMI_GPU_FIELDS, vals)))

        if not gpus:
            return {"hostname": hostname, "error": "No GPUs found"}

        # 解析 进程 信息
        processes_by_uuid = {}
        all_pids = set()

        for line in proc_lines:
            if not line.strip(): continue
            vals = [v.strip() for v in line.split(',')]
            p_info = dict(zip(NVIDIA_SMI_PROC_FIELDS, vals))

            uuid = p_info['gpu_uuid']
            if uuid not in processes_by_uuid: processes_by_uuid[uuid] = []
            processes_by_uuid[uuid].append(p_info)
            all_pids.add(p_info['pid'])

        # 2. 只有当有进程时，才执行 ps 命令获取用户名
        pid_to_user = {}
        if all_pids:
            pids_str = ",".join(all_pids)
            # 优化：同时获取 PID 和 User，确保映射准确
            # ps -o pid=,user= -p 123,456
            cmd_ps = f"ps -o pid=,user= -p {pids_str}"
            stdin, stdout, stderr = client.exec_command(cmd_ps, timeout=5)
            ps_out = stdout.read().decode('utf-8').strip()

            for line in ps_out.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    pid_to_user[parts[0]] = parts[1]

        # 3. 组装最终数据
        final_gpu_list = []
        for gpu in gpus:
            mem_used = int(gpu['memory.used'])
            mem_total = int(gpu['memory.total'])

            # 处理该 GPU 上的进程
            procs = processes_by_uuid.get(gpu['uuid'], [])
            proc_strs = []
            for p in procs:
                pid = p['pid']
                user = pid_to_user.get(pid, 'unknown')
                mem = int(float(p['used_gpu_memory']))
                name = p['process_name'].replace(' ', '')
                proc_strs.append(f"{user}({name},{mem}M)")

            final_gpu_list.append({
                "index": str(int(gpu['index'])),
                "name": gpu['name'],
                "temperature.gpu": int(gpu['temperature.gpu']),
                "utilization.gpu": int(gpu['utilization.gpu']),
                "memory.used": mem_used,
                "memory.total": mem_total,
                "memory": round((mem_used / mem_total) * 100) if mem_total > 0 else 0,
                "power.draw": int(float(gpu['power.draw'])),
                "enforced.power.limit": int(float(gpu['power.limit'])),
                "user_processes": " ".join(proc_strs),
                "users": len(proc_strs)
            })

        return {"hostname": hostname, "gpus": final_gpu_list}

    except Exception as e:
        print(f"Error fetching {hostname}: {e}")
        with SSH_LOCK:
            SSH_CLIENTS.pop(hostname, None)  # 移除坏连接
        # 返回错误状态结构，防止前端报错
        return {
            "hostname": hostname,
            "gpus": [{
                "index": "Err", "name": "Connection Error",
                "temperature.gpu": 0, "utilization.gpu": 0,
                "memory.used": 0, "memory.total": 0, "memory": 0,
                "power.draw": 0, "enforced.power.limit": 0,
                "user_processes": str(e), "users": 0
            }]
        }


def background_monitor_loop():
    """后台线程：每3秒轮询一次所有服务器"""
    global GLOBAL_GPU_STATS
    print("Starting background monitor thread...")
    while True:
        start_time = time.time()

        # 并发采集
        results = []
        with ThreadPoolExecutor(max_workers=len(SERVERS) or 1) as executor:
            futures = executor.map(fetch_single_server_data, SERVERS)
            results = list(futures)

        # 更新全局缓存
        with CACHE_LOCK:
            GLOBAL_GPU_STATS = results

        # 计算耗时，确保间隔稳定
        elapsed = time.time() - start_time
        sleep_time = max(0.5, 3.0 - elapsed)  # 至少休息0.5秒，尽量保持3秒周期
        time.sleep(sleep_time)


# ================= Flask 路由 =================

@app.route('/')
def dashboard():
    return render_template('index.html')


@app.route('/api/gpustat/all')
def api_gpu_data():
    # API 现在非常快，因为它只读取内存
    with CACHE_LOCK:
        # 返回缓存数据的副本
        return jsonify(GLOBAL_GPU_STATS)


if __name__ == '__main__':
    # 启动后台采集线程（设置为 Daemon，随主进程结束而结束）
    if SERVERS:
        monitor_thread = threading.Thread(target=background_monitor_loop, daemon=True)
        monitor_thread.start()
    else:
        print("Warning: No servers found in config.ini")

    app.run(debug=False, host='0.0.0.0', port=8888)
