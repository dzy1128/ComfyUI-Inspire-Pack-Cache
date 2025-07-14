import requests
import json
import time

# ComfyUI 服务器地址
ip_addr = requests.get('https://ifconfig.me/ip').text.strip()
SERVER_ADDRESS = ip_addr + ":8188"
# 你的工作流 API JSON 文件路径
WORKFLOW_API_FILE = "workflows/缓存模型.json"

def queue_prompt(prompt_workflow):
    """向 ComfyUI API 发送请求"""
    try:
        p = {"prompt": prompt_workflow}
        data = json.dumps(p).encode('utf-8')
        req = requests.post(f"http://{SERVER_ADDRESS}/prompt", data=data)
        req.raise_for_status() # 如果请求失败则抛出异常
        return req.json()
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to ComfyUI: {e}")
        return None

def queue_workflow():
    # 等待 ComfyUI 服务器启动
    print("等待 ComfyUI 服务器准备就绪...")
    while True:
        try:
            response = requests.get(f"http://{SERVER_ADDRESS}/queue")
            if response.status_code == 200:
                print("ComfyUI 服务器已准备就绪。")
                break
        except requests.ConnectionError:
            time.sleep(1)  # 每秒重试一次

    # 加载工作流 API 文件
    try:
        with open(WORKFLOW_API_FILE, 'r') as f:
            workflow = json.load(f)
    except FileNotFoundError:
        print(f"错误：未找到工作流文件 {WORKFLOW_API_FILE}")
        return

    # 将工作流添加到队列
    print("正在将工作流加入队列...")
    response = queue_prompt(workflow)
    if response:
        prompt_id = response.get('prompt_id')
        print("成功将工作流加入队列。")
        print(f"工作流 ID: {prompt_id}")
        
        # 等待工作流开始执行
        print("等待工作流开始执行...")
        prompt_started = False
        
        # 等待工作流执行完成
        while True:
            try:
                queue_status = requests.get(f"http://{SERVER_ADDRESS}/queue")
                queue_data = queue_status.json()
                
                running_items = queue_data.get('running_items', [])
                queue_items = queue_data.get('queue_items', [])
                
                # 检查我们的prompt是否在运行中
                is_running = any(item.get('prompt_id') == prompt_id for item in running_items)
                is_queued = any(item.get('prompt_id') == prompt_id for item in queue_items)
                
                # 确认工作流已经开始执行过
                if is_running and not prompt_started:
                    prompt_started = True
                    print("工作流已开始执行...")
                
                # 只有在确认工作流曾经开始执行，但现在既不在运行也不在队列中时，才认为完成
                if prompt_started and not is_running and not is_queued:
                    print("工作流执行完成。")
                    break
                
                # 如果还在队列中或正在运行，继续等待
                if is_running or is_queued:
                    time.sleep(1)
                    continue
                
                # 如果从未见到工作流进入运行状态，但现在队列中找不到了，可能出了问题
                if not prompt_started and not is_running and not is_queued:
                    # 等待几秒再次确认，避免网络延迟等问题
                    time.sleep(3)
                    queue_status = requests.get(f"http://{SERVER_ADDRESS}/queue")
                    queue_data = queue_status.json()
                    
                    running_items = queue_data.get('running_items', [])
                    queue_items = queue_data.get('queue_items', [])
                    
                    if not any(item.get('prompt_id') == prompt_id for item in running_items) and \
                       not any(item.get('prompt_id') == prompt_id for item in queue_items):
                        print("警告：工作流似乎从未开始执行就消失了，可能遇到了问题。")
                        break
                
                time.sleep(1)
            except Exception as e:
                print(f"检查队列状态时出错: {e}")
                time.sleep(5)  # 出错时等待稍长时间再重试
    else:
        print("将工作流加入队列失败。")

def queue_workflow_simple():
    """简化版的工作流启动函数，只负责将工作流加入队列"""
    try:
        # 加载工作流 API 文件
        with open(WORKFLOW_API_FILE, 'r') as f:
            workflow = json.load(f)
        
        # 将工作流添加到队列
        p = {"prompt": workflow}
        data = json.dumps(p).encode('utf-8')
        req = requests.post(f"http://{SERVER_ADDRESS}/prompt", data=data)
        req.raise_for_status()
        print(f"成功将工作流加入队列: {req.json().get('prompt_id')}")
        return True
    except Exception as e:
        print(f"启动工作流出错: {e}")
        return False
