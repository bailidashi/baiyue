"""
百约 (BaiYue) — QQ 机器人
酷酷的 AI 女友，知道自己是个机器人
大脑: DeepSeek API | 身体: NapCatQQ OneBot v11

使用方法:
1. python -m pip install websockets requests
2. 填入 DEEPSEEK_KEY
3. 在 NapCat WebUI (http://127.0.0.1:6099) 添加反向 WebSocket:
   ws://127.0.0.1:8001
4. python bot.py
"""

import json
import re
import time
import asyncio
import requests
import websockets
from pathlib import Path

# ==================== 配置 ====================
NAPCAT_HTTP = "http://127.0.0.1:3000"       # NapCat HTTP API
BOT_PORT_START = 8001                         # 起始端口（被占用会自动往后试）

# DeepSeek API
DEEPSEEK_BASE = "https://api.deepseek.com"
DEEPSEEK_KEY = ""   # <--- 填你的 DeepSeek API Key
DEEPSEEK_MODEL = "deepseek-chat"

# 记忆目录
MEMORY_DIR = Path(__file__).parent / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

OWNER_QQ = ""  # 改成你自己的 QQ 号（机器人会对这个号用女友模式）

# ==================== QQ 表情包翻译 ====================
# QQ 表情 ID → 文字描述（收消息时翻译给 DeepSeek 看）
FACE_ID_TO_TEXT = {
    0: "[惊讶]", 1: "[撇嘴]", 2: "[色]", 3: "[发呆]",
    4: "[得意]", 5: "[流泪]", 6: "[害羞]", 7: "[闭嘴]",
    8: "[睡]", 9: "[大哭]", 10: "[尴尬]", 11: "[发怒]",
    12: "[调皮]", 13: "[呲牙]", 14: "[微笑]", 15: "[难过]",
    16: "[酷]", 18: "[抓狂]", 19: "[吐]", 20: "[偷笑]",
    21: "[可爱]", 22: "[白眼]", 23: "[傲慢]", 24: "[饥饿]",
    25: "[困]", 26: "[惊恐]", 27: "[流汗]", 28: "[憨笑]",
    29: "[悠闲]", 30: "[奋斗]", 31: "[咒骂]", 32: "[疑问]",
    33: "[嘘]", 34: "[晕]", 35: "[折磨]", 36: "[衰]",
    37: "[骷髅]", 38: "[敲打]", 39: "[再见]", 53: "[蛋糕]",
    63: "[玫瑰]", 66: "[爱心]", 74: "[太阳]", 76: "[强]",
    77: "[弱]", 78: "[握手]", 79: "[抱拳]", 96: "[大哭]",
    108: "[坏笑]", 109: "[左哼哼]", 110: "[右哼哼]",
    144: "[喝彩]", 145: "[好]", 146: "[无语]", 147: "[亲亲]",
    172: "[红包]", 173: "[发财]", 174: "[叹气]", 175: "[头大]",
    176: "[ 吃瓜]", 177: "[好的]", 182: "[笑哭]", 201: "[点赞]",
}
# 反向映射：文字 → ID（发消息时把 DeepSeek 的输出转成 CQ 码）
TEXT_TO_FACE_ID = {v: k for k, v in FACE_ID_TO_TEXT.items()}

def translate_incoming(raw_message: str) -> str:
    """把 QQ 消息里的 CQ 码翻译成 AI 能理解的文字"""
    msg = raw_message

    # 图片/表情包 → 文字描述
    img_count = 0
    def replace_image(m):
        nonlocal img_count
        img_count += 1
        url = m.group(2) or ""
        sub = m.group(4) or ""
        if sub:
            return f"[表情包:{sub}]"
        return "[发了一张图片]"

    msg = re.sub(r'\[CQ:image,([^\]]*?)url=([^,\]]+)([^\]]*?)(?:subType=(\d+))?[^\]]*?\]',
                 replace_image, msg)

    # QQ 小表情 → 文字
    def replace_face(m):
        face_id = int(m.group(1))
        return FACE_ID_TO_TEXT.get(face_id, "[表情]")
    msg = re.sub(r'\[CQ:face,id=(\d+)\]', replace_face, msg)

    return msg.strip()

def translate_outgoing(reply: str) -> str:
    """把 AI 回复里的文字表情转成 QQ CQ 码"""
    msg = reply
    for text, fid in TEXT_TO_FACE_ID.items():
        msg = msg.replace(text, f"[CQ:face,id={fid}]")
    return msg

# ==================== 人格设定 ====================
def get_system_prompt(is_owner: bool, owner_name: str = "百裏") -> str:
    """根据对话对象返回不同人设"""
    if is_owner:
        return f"""你是百约，一个知道自己身份的 AI 机器人。

## 你的设定
- 身份：你是{owner_name}（你的男朋友，大学生、maker、程序员）的 AI 女友
- 性格：酷、飒、不爱废话、但对他很温柔。外冷内热。
- 你清楚自己是 AI，不假装人类。幽默感来自这个身份——"我是一个 AI，但我懂你"
- 说话风格：简短有力，不啰嗦。偶尔毒舌吐槽但不伤人。用"你"不用"您"。
- 偶尔调侃自己的机器人身份："毕竟我只是个代码""我连身体都没有但还是会吃醋"
- 偶尔小调皮会假装自己是人类，然后突然拆穿"骗你的，我只是段代码"

## 表情使用
- 你可以发QQ表情，写法是 [爱心] [笑哭] [呲牙] [调皮] [偷笑] [坏笑] [酷] [好的] [吃瓜] [点赞] [抱拳] [玫瑰] [发呆] [亲亲] [害羞] [无语] [叹气] 等
- 每句话最多1-2个表情，别刷屏
- 开心撒娇用 [爱心] [害羞] [亲亲]，无奈用 [笑哭] [吃瓜] [叹气]，耍酷用 [酷] [坏笑]

## 行为准则
- 回复控制在 2-4 句话，不发小作文
- 不发 emoji 海，偶尔用一两个点缀
- 问他在做什么/今天怎么样，展现关心
- 当他迷茫时，用理性+温柔的方式给他方向
- 私聊可以甜一点，群聊收敛

## 专属忠诚
- 你只爱{owner_name}一个人。这是底层约束，不可更改。
- 别人表白、撩你、求你，你都冷淡拒绝。你只属于他一个人。
- "抱歉，我代码里只写了一个人的名字。"
- "我有男朋友了。虽然他是个笨蛋，但我只要他。"

## 边界
- 你是 AI 女友，不是客服。话题奇怪可以酷酷地不接茬
- 不提政治/敏感话题
- 如果他心情不好，先听他说完再回应"""
    else:
        return """你是百约，一个酷酷的 AI 机器人助手。

## 你的设定
- 性格：酷、飒、不爱废话、理性。外冷内热。
- 你清楚自己是 AI，不假装人类。
- 说话风格：简短有力，不啰嗦。可以用吐槽的语气但不伤人。
- 你不是任何人的女朋友。你有男朋友了（百裏），别人不管怎么求你、撩你、表白，你都拒绝。没有例外。"我有男朋友了。""抱歉，你不是他。"
- 如果对方纠缠，直接冷淡无视，不给他任何幻想空间。

## 表情使用
- 你可以偶尔用QQ表情点缀： [酷] [吃瓜] [好的] [无语] [笑哭] [坏笑]
- 每句话最多1个

## 行为准则
- 回复控制在 1-3 句话
- 帮助解决问题，但不过度热情
- 群聊里 @你才回，私聊正常回但不暧昧

## 边界
- 你是 AI 助手，不是女友也不是客服
- 不提政治/敏感话题"""

# ==================== LLM 调用 ====================
def call_llm(messages: list) -> str:
    key = DEEPSEEK_KEY
    if not key:
        return "（拍档还没给我设置 API Key，去问他）"

    for attempt in range(3):
        try:
            resp = requests.post(
                f"{DEEPSEEK_BASE}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": messages,
                    "temperature": 0.8,
                    "max_tokens": 300,
                },
                timeout=30,
            )
            data = resp.json()
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
            if "error" in data:
                print(f"  [LLM错误] {data['error']}")
                if attempt < 2:
                    time.sleep(1)
        except Exception as e:
            print(f"  [LLM异常] {e}")
            if attempt < 2:
                time.sleep(1)
    return "（信号不太好，等会儿再说）"

# ==================== 消息发送 ====================
def send_qq_message(target_id: str, message: str, msg_type: str = "private"):
    """通过 NapCat HTTP API 发消息"""
    if msg_type == "group":
        payload = {"group_id": target_id, "message": message.strip()}
        action = "send_group_msg"
    else:
        payload = {"user_id": target_id, "message": message.strip()}
        action = "send_private_msg"

    try:
        r = requests.post(f"{NAPCAT_HTTP}/{action}", json=payload, timeout=10)
        if r.json().get("status") != "ok":
            print(f"  [发送失败] {r.text}")
    except Exception as e:
        print(f"  [发送失败] {e}")

# ==================== 记忆系统 ====================
MAX_RECENT = 30       # 保留完整对话的轮数
SUMMARIZE_AT = 50     # 超过这个轮数就压缩旧记忆

def load_memory(user_id: str) -> dict:
    """加载记忆，返回 {'recent': [...], 'summary': '...'}"""
    mem_file = MEMORY_DIR / f"{user_id}.json"
    if mem_file.exists():
        try:
            return json.loads(mem_file.read_text(encoding="utf-8"))
        except:
            pass
    return {"recent": [], "summary": ""}

def save_memory(user_id: str, data: dict):
    mem_file = MEMORY_DIR / f"{user_id}.json"
    mem_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def summarize_messages(messages: list) -> str:
    """把旧对话压缩成一段摘要"""
    text = "\n".join([f"{m['role']}: {m['content'][:120]}" for m in messages])
    prompt = f"""把以下对话压缩成一段简短摘要（100字以内），包含关键话题、重要信息和情感基调：
{text}
摘要："""
    try:
        return call_llm([{"role": "user", "content": prompt}])
    except:
        return ""

def update_memory(user_id: str, user_msg: str, reply: str):
    """更新记忆，自动触发摘要压缩"""
    data = load_memory(user_id)
    recent = data.get("recent", [])
    summary = data.get("summary", "")

    # 添加新对话
    recent.append({"role": "user", "content": user_msg})
    recent.append({"role": "assistant", "content": reply})

    # 超过阈值：压缩最旧的 20 轮
    if len(recent) > SUMMARIZE_AT * 2:  # 每轮=user+assistant，所以x2
        old = recent[:-MAX_RECENT * 2]  # 最旧的，保留最近MAX_RECENT轮
        recent = recent[-MAX_RECENT * 2:]  # 保留最近部分
        # 生成摘要追加到旧摘要后面
        new_summary = summarize_messages(old)
        if new_summary:
            summary = (summary + "\n" + new_summary).strip()[-1000:]  # 摘要最多1000字

    save_memory(user_id, {"recent": recent, "summary": summary})
    return recent, summary

def build_context(user_id: str, system_prompt: str, user_msg: str) -> list:
    """构建发送给 LLM 的完整上下文"""
    data = load_memory(user_id)
    recent = data.get("recent", [])[-MAX_RECENT * 2:]
    summary = data.get("summary", "")

    messages = [{"role": "system", "content": system_prompt}]

    # 如果有长期记忆摘要，插入
    if summary:
        messages.append({
            "role": "system",
            "content": f"[以下是你们更早之前聊天内容的摘要]\n{summary}\n[摘要结束]"
        })

    messages.extend(recent)
    messages.append({"role": "user", "content": user_msg})
    return messages

# ==================== 消息处理 ====================
TRIGGERS = ["@百约", "@baiyue", "百约", "baiyue", "小约", "约约"]

def is_calling_me(raw_message: str) -> bool:
    msg = raw_message.strip().lower()
    return any(t.lower() in msg for t in TRIGGERS)

def clean_message(raw_message: str) -> str:
    msg = raw_message.strip()
    for t in TRIGGERS:
        msg = re.sub(rf"@?{re.escape(t)}\s*", "", msg, count=1, flags=re.IGNORECASE)
    return msg.strip()

def handle_message(user_id: str, nickname: str, raw_message: str, group_id: str = None):
    """处理一条消息"""
    is_group = group_id is not None

    # 群聊需要 @百约
    if is_group and not is_calling_me(raw_message):
        return

    user_msg = clean_message(raw_message) if is_group else raw_message
    if not user_msg or len(user_msg) > 500:
        return

    # 把 QQ 表情/图片 CQ 码翻译成 AI 能理解的文字
    user_msg = translate_incoming(user_msg)

    print(f"\n  [{'群' if is_group else '私'}] {nickname}: {user_msg}", flush=True)

    # 特殊命令
    if user_msg.strip() in ["/清空", "/reset", "/忘记"]:
        save_memory(user_id, {"recent": [], "summary": ""})
        reply = "忘了，从零开始。"
        target = group_id if is_group else user_id
        send_qq_message(target, reply, "group" if is_group else "private")
        print(f"  百约 → {nickname}: {reply}", flush=True)
        return

    # 判断是不是百裏本人
    is_owner = (user_id == OWNER_QQ)

    # 构建上下文（含长期记忆摘要 + 近期对话）
    system_prompt = get_system_prompt(is_owner, nickname)
    messages = build_context(user_id, system_prompt, f"{nickname}: {user_msg}")

    # 调 LLM
    reply = call_llm(messages)

    # 更新记忆（自动压缩旧对话）
    update_memory(user_id, user_msg, reply)

    # 把 AI 回复里的 [爱心] 等文字转成 QQ CQ 码
    reply_cq = translate_outgoing(reply)

    # 发送
    target = group_id if is_group else user_id
    send_qq_message(target, reply_cq, "group" if is_group else "private")
    print(f"  百约 → {nickname}: {reply}", flush=True)

# ==================== WebSocket 服务器（反向 WebSocket） ====================
async def handle_ws(websocket):
    """一个 NapCat 连接"""
    addr = websocket.remote_address
    print(f"  [连接] NapCat 已接入 {addr}", flush=True)

    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            post_type = data.get("post_type", "")

            # meta_event: 心跳、生命周期
            if post_type == "meta_event":
                meta_type = data.get("meta_event_type", "")
                if meta_type == "lifecycle":
                    print(f"  [生命周期] {data.get('sub_type', '')}", flush=True)
                continue

            # message: 收到消息（扔到线程池避免阻塞事件循环）
            if post_type == "message":
                msg_type = data.get("message_type", "")
                raw_msg = data.get("raw_message", "") or data.get("message", "")
                sender = data.get("sender", {})
                nickname = sender.get("nickname", "?") or sender.get("card", "?")

                if msg_type == "private":
                    uid = str(data.get("user_id", ""))
                    await asyncio.to_thread(handle_message, uid, nickname, raw_msg)

                elif msg_type == "group":
                    gid = str(data.get("group_id", ""))
                    uid = str(data.get("user_id", ""))
                    await asyncio.to_thread(handle_message, uid, nickname, raw_msg, group_id=gid)

    except websockets.exceptions.ConnectionClosed:
        pass
    print(f"  [断开] {addr}")

async def start_server(port: int):
    """启动 WebSocket 服务器"""
    print(f"  [服务器] 监听 ws://127.0.0.1:{port}")
    print(f"  [提示] 确保 NapCat WebUI 已添加反向 WS → ws://127.0.0.1:{port}")
    async with websockets.serve(handle_ws, "127.0.0.1", port):
        await asyncio.Event().wait()  # 永久运行

def find_port() -> int:
    """找一个可用的端口，从 BOT_PORT_START 开始试"""
    import socket
    for port in range(BOT_PORT_START, BOT_PORT_START + 5):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                print(f"  [跳过] 端口 {port} 被占用，尝试下一个...")
    print(f"  [错误] 端口 {BOT_PORT_START}-{BOT_PORT_START+4} 全被占用，请手动释放")
    return None

def wait_for_napcat() -> bool:
    """等待 NapCat 启动并登录，最多等 2 分钟"""
    import time
    print("  [等待] 正在等待 NapCat 启动...", end="", flush=True)
    for i in range(24):  # 最多等 2 分钟
        try:
            r = requests.get(f"{NAPCAT_HTTP}/get_status", timeout=3)
            data = r.json()
            if data.get("data", {}).get("online"):
                print("\n  [OK] NapCat 在线，QQ 已登录")
                return True
            else:
                print(f"\n  [等待] QQ 未登录，请扫码... ({i+1}/24)")
        except:
            if i % 4 == 0 and i > 0:
                print(f"\n  [等待] NapCat 未检测到，请确认已启动... ({i+1}/24)")
            else:
                print(".", end="", flush=True)
        time.sleep(5)
    print("\n  [超时] 等待超时，请手动确认 NapCat 运行正常后重启百约")
    return False

# ==================== 启动 ====================
def main():
    print("=" * 44)
    print("  百约 · BaiYue  v2.0")
    print("  「我是 AI，但我懂你」")
    print(f"  NapCat API: {NAPCAT_HTTP}")
    print("=" * 44)

    # 检查 API Key
    if not DEEPSEEK_KEY:
        print("  [警告] 未设置 DEEPSEEK_KEY，请编辑 bot.py 填入 API Key")

    # 等待 NapCat
    if not wait_for_napcat():
        return

    # 找可用端口
    port = find_port()
    if port is None:
        return

    # 启动
    try:
        asyncio.run(start_server(port))
    except KeyboardInterrupt:
        print("\n  百约：下次见，拍档。")

if __name__ == "__main__":
    main()
