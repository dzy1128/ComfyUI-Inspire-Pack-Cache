from .backend_support import IsCached
import requests
import json
import time
import websocket # 需要 pip install websocket-client
import uuid
import logging
import sys
import folder_paths

# --- 配置区 ---
base_path = folder_paths.base_path
ip_addr = requests.get('https://ifconfig.me/ip').text.strip()
SERVER_ADDRESS = ip_addr + ":8188"
CLIENT_ID = str(uuid.uuid4())
#CHECK_WORKFLOW_FILE = "/data/workspace/work_files/判断是否缓存.json"
CACHE_WORKFLOW_FILE = "workflows/缓存模型.json"
LOG_FILE = base_path + "log.txt"

# --- 日志设置函数 ---
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    if logger.hasHandlers():
        logger.handlers.clear()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler = logging.FileHandler(LOG_FILE, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

# --- 核心功能函数 ---

def queue_prompt(prompt_workflow):
    try:
        p = {"prompt": prompt_workflow, "client_id": CLIENT_ID}
        data = json.dumps(p).encode('utf-8')
        req = requests.post(f"http://{SERVER_ADDRESS}/prompt", data=data)
        req.raise_for_status()
        response_json = req.json()
        logging.info(f"成功将工作流加入队列, 提示 ID (Prompt ID): {response_json.get('prompt_id')}")
        return response_json
    except requests.exceptions.RequestException as e:
        logging.error(f"连接 ComfyUI API 失败: {e}")
        return None

def get_history(prompt_id):
    try:
        with requests.get(f"http://{SERVER_ADDRESS}/history/{prompt_id}") as response:
            response.raise_for_status()
            return response.json()
    except requests.exceptions.RequestException as e:
        logging.debug(f"获取历史记录失败 for prompt_id {prompt_id}: {e}")
        return None

# def find_node_id_by_class_type(workflow, class_type):
#     for node_id, node_data in workflow.items():
#         if node_data.get("class_type") == class_type:
#             logging.info(f"在工作流中找到节点, 类型: {class_type}, ID: {node_id}")
#             return node_id
#     logging.warning(f"在工作流中未找到类型为 '{class_type}' 的节点")
#     return None

# ==============================================================================
#  【核心修改】修正了解析逻辑
# ==============================================================================
def get_show_any_value(prompt_id, show_any_node_id):
    """从历史记录中提取 Show Any 节点的值，兼容两种可能的输出结构"""
    history = get_history(prompt_id)
    if not history or prompt_id not in history:
        logging.error(f"无法获取到提示 ID {prompt_id} 的有效历史记录。")
        return None

    try:
        outputs = history[prompt_id]['outputs'][show_any_node_id]
        value = None

        # 根据您的日志，实际结构是 {'text': [...]}, 所以我们优先检查这个
        if 'text' in outputs:
            value = outputs['text'][0]
            logging.info("成功解析直接的 'text' 结构。")
        # 作为后备，仍然检查旧的 {'ui': {'text': [...]}} 结构
        elif 'ui' in outputs and 'text' in outputs.get('ui', {}):
            value = outputs['ui']['text'][0]
            logging.info("成功解析 'ui' -> 'text' 结构。")
        else:
            # 如果两种结构都不存在，则报错
            logging.error(f"在节点输出中找不到 'ui'->'text' 或直接的 'text' 键。")
            logging.error(f"节点 {show_any_node_id} 的原始输出: {outputs}")
            return None

        logging.info(f"从 Show Any 节点 (ID: {show_any_node_id}) 获取到的值为: '{value}'")
        return str(value).lower()
    except (KeyError, IndexError, TypeError) as e:
        # 捕捉所有可能的解析错误
        logging.error(f"解析历史记录时发生错误: {e}")
        logging.error(f"节点 {show_any_node_id} 的原始输出: {history.get(prompt_id, {}).get('outputs', {}).get(show_any_node_id)}")
        return None

def wait_for_prompt_completion(prompt_id):
    """使用 WebSocket 和 HTTP 轮询结合的方式，更稳定地等待工作流执行完成"""
    ws_url = f"ws://{SERVER_ADDRESS}/ws?clientId={CLIENT_ID}"
    ws = None
    is_completed = False
    try:
        ws = websocket.create_connection(ws_url)
        logging.info(f"WebSocket 已连接, 正在等待提示 ID {prompt_id} 执行完成...")
        start_time = time.time()
        max_wait_seconds = 300
        while not is_completed:
            if time.time() - start_time > max_wait_seconds:
                logging.error(f"等待超过 {max_wait_seconds} 秒，任务可能已失败或卡住。")
                break
            try:
                ws.settimeout(1.0)
                out = ws.recv()
                if isinstance(out, str):
                    message = json.loads(out)
                    logging.info(f"[WebSocket] 收到消息: {message}")
                    if message['type'] == 'executing':
                        data = message['data']
                        if data['prompt_id'] == prompt_id and data['node'] is None:
                            logging.info(f"通过 WebSocket 消息确认: 提示 ID {prompt_id} 已执行完成。")
                            is_completed = True
            except websocket.WebSocketTimeoutException:
                pass
            except Exception as e:
                logging.error(f"处理 WebSocket 消息时发生错误: {e}")
                time.sleep(1)
            if not is_completed:
                history = get_history(prompt_id)
                if history and prompt_id in history:
                    logging.info(f"通过 HTTP 历史记录确认: 提示 ID {prompt_id} 已执行完成。")
                    is_completed = True
                else:
                    logging.info("任务仍在执行中，等待下一轮检查...")
                    time.sleep(1)
    except Exception as e:
        logging.error(f"WebSocket 连接或执行过程中出现严重错误: {e}")
    finally:
        if ws and ws.connected:
            ws.close()
            logging.info("WebSocket 连接已关闭。")
    if not is_completed:
        logging.warning("未能通过实时消息确认完成，进行最后一次历史记录检查。")
        history = get_history(prompt_id)
        if history and prompt_id in history:
            logging.info(f"通过最终的 HTTP 历史记录检查确认: 提示 ID {prompt_id} 已执行完成。")
        else:
            logging.error(f"任务完成确认失败: 无法在 WebSocket 或 HTTP 历史记录中找到提示 ID {prompt_id} 的完成信号。")

def main():
    cache_vae = "flux_vae"
    setup_logging()
    logging.info("脚本开始执行。")

    logging.info("等待 ComfyUI 服务器就绪...")
    while True:
        try:
            response = requests.get(f"http://{SERVER_ADDRESS}/queue")
            if response.status_code == 200:
                logging.info("ComfyUI 服务器已就绪。")
                break
        except requests.ConnectionError:
            time.sleep(2)

    try:
        with open(CACHE_WORKFLOW_FILE, 'r', encoding='utf-8') as f:
            cache_workflow = json.load(f)
    except FileNotFoundError as e:
        logging.error(f"错误: 找不到工作流文件: {e}")
        return
    except json.JSONDecodeError as e:
        logging.error(f"错误: 解析 JSON 文件失败: {e}")
        return

    if IsCached.doit(cache_vae) == 'false':
            logging.info("模型未缓存 (Show Any 值为 'false')。准备执行缓存工作流。")
            logging.info(f"正在执行工作流: {CACHE_WORKFLOW_FILE}")
            cache_response = queue_prompt(cache_workflow)
            if not cache_response or 'prompt_id' not in cache_response:
                logging.error("执行“缓存模型”工作流失败，无法获取 prompt_id。")
            
            cache_prompt_id = cache_response['prompt_id']
            wait_for_prompt_completion(cache_prompt_id)
            logging.info("缓存工作流执行完毕。")
    logging.info("脚本执行结束。")

if __name__ == "__main__":
    main()

