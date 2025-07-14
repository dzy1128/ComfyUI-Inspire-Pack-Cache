import requests
import json
import time
import uuid
import server
import os
import threading
import traceback

# ComfyUI 服务器地址
ip_addr = requests.get('https://ifconfig.me/ip').text.strip()
SERVER_ADDRESS = "27.148.182.150" + ":8188"
# 你的工作流 API JSON 文件路径
WORKFLOW_API_FILE = "user/default/workflows/api_workflows/缓存模型.json"


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
    p = os.getcwd()
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
        print(f"错误：{p}未找到工作流文件 {WORKFLOW_API_FILE}")
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

# 将 queue_workflow 修改为异步执行
def queue_workflow_async():
    """异步执行工作流"""
    def run_workflow():
        try:
            print("开始执行缓存工作流...")
            queue_workflow_with_debug()
            print("缓存工作流执行完成")
        except Exception as e:
            print(f"执行缓存工作流时出错: {e}")
    # 在新线程中执行
    thread = threading.Thread(target=run_workflow, daemon=True)
    thread.start()

#comfyui内部原生方法
def queue_workflow_internally():
    p = os.getcwd()
    """直接使用 ComfyUI 内部函数将工作流加入队列"""
    try:
        # 1. 加载工作流文件
        with open(WORKFLOW_API_FILE, 'r') as f:
            prompt = json.load(f)

        # 2. 获取服务器实例和队列实例
        p_server = server.PromptServer.instance
        prompt_queue = p_server.prompt_queue

        # 3. 为这个工作流生成一个唯一的 ID
        prompt_id = str(uuid.uuid4())
        
        # 4. 准备要插入队列的数据
        # 结构为 (execution_number, prompt_id, prompt, extra_data, client_address)
        extra_data = {} # 额外数据，这里为空
        # 从队列获取下一个执行编号
        number = prompt_queue.get_latest_queue_number() + 1
        
        # 模拟一个来自服务器内部的请求地址
        client_address = ("27.148.182.150", 0) 

        # 5. 将任务放入队列
        prompt_queue.put((number, prompt_id, prompt, extra_data, client_address))

        print(f"内部调用：成功将工作流加入队列。工作流 ID: {prompt_id}")
        return True, f"工作流已成功加入队列，ID: {prompt_id}"

    except FileNotFoundError:
        error_msg = f"错误：{p},未找到工作流文件 {WORKFLOW_API_FILE}"
        print(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"内部调用时发生未知错误: {e}"
        print(error_msg)
        return False, error_msg
    
def queue_workflow_with_debug():
    """带详细调试信息的工作流执行函数"""
    print("=== 开始执行 queue_workflow_with_debug ===")
    
    try:
        # 获取服务器地址
        print("正在获取服务器地址...")
        print(f"服务器地址: {SERVER_ADDRESS}")
        
        # 检查工作流文件
        print(f"检查工作流文件: {WORKFLOW_API_FILE}")
        
        import os
        if not os.path.exists(WORKFLOW_API_FILE):
            print(f"错误：工作流文件不存在: {WORKFLOW_API_FILE}")
            print(f"当前工作目录: {os.getcwd()}")
            print(f"workflows目录内容: {os.listdir('workflows') if os.path.exists('workflows') else '目录不存在'}")
            return
        
        # 等待服务器准备就绪
        print("等待 ComfyUI 服务器准备就绪...")
        max_retries = 30
        for i in range(max_retries):
            try:
                response = requests.get(f"http://{SERVER_ADDRESS}/queue", timeout=5)
                if response.status_code == 200:
                    print("ComfyUI 服务器已准备就绪。")
                    break
                else:
                    print(f"服务器响应状态码: {response.status_code}")
            except requests.ConnectionError as e:
                print(f"连接尝试 {i+1}/{max_retries}: {e}")
                time.sleep(2)
        else:
            print("错误：无法连接到 ComfyUI 服务器")
            return

        # 加载工作流
        print("加载工作流文件...")
        with open(WORKFLOW_API_FILE, 'r', encoding='utf-8') as f:
            workflow = json.load(f)
        print("工作流文件加载成功")

        # 提交工作流
        print("提交工作流到队列...")
        p = {"prompt": workflow}
        data = json.dumps(p).encode('utf-8')
        req = requests.post(f"http://{SERVER_ADDRESS}/prompt", data=data, timeout=10)
        req.raise_for_status()
        
        response_data = req.json()
        prompt_id = response_data.get('prompt_id')
        print(f"工作流提交成功，ID: {prompt_id}")
        
        # 监控执行状态（简化版本，避免无限循环）
        print("监控工作流执行状态...")
        for i in range(60):  # 最多监控60秒
            try:
                queue_status = requests.get(f"http://{SERVER_ADDRESS}/queue", timeout=5)
                queue_data = queue_status.json()
                
                running_items = queue_data.get('running_items', [])
                queue_items = queue_data.get('queue_items', [])
                
                is_running = any(item.get('prompt_id') == prompt_id for item in running_items)
                is_queued = any(item.get('prompt_id') == prompt_id for item in queue_items)
                
                print(f"状态检查 {i+1}: 运行中={is_running}, 队列中={is_queued}")
                
                if not is_running and not is_queued:
                    print("工作流执行完成或已从队列中移除")
                    break
                    
                time.sleep(1)
            except Exception as e:
                print(f"状态检查出错: {e}")
                break
        
        print("=== queue_workflow_with_debug 执行完成 ===")
        
    except Exception as e:
        print(f"执行工作流时发生异常: {e}")
        print(f"异常详情: {traceback.format_exc()}")