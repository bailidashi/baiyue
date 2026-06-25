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
BOT_PORT = 8001                               # 百约 WebSocket 服务器端口

# DeepSeek API
DEEPSEEK_BASE = "https://api.deepseek.com"
DEEPSEEK_KEY = ""   # <--- 填你的 DeepSeek API Key
DEEPSEEK_MODEL = "deepseek-chat"

# 记忆目录
MEMORY_DIR = Path(__file__).parent / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

OWNER_QQ = "3154997545"  # 百裏的 QQ 号——只有他是男朋友

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
    176: "[吃瓜]", 177: "[好的]", 182: "[笑哭]", 201: "[点赞]",
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
- 你不是任何人的女朋友。如果对方撩你，可以冷淡回应或者无视。

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
def load_memory(user_id: str) -> list:
    mem_file = MEMORY_DIR / f"{user_id}.json"
    if mem_file.exists():
        try:
            data = json.loads(mem_file.read_text(encoding="utf-8"))
            return data[-30:]  # 最近30轮
        except:
            pass
    return []

def save_memory(user_id: str, memory: list):
    mem_file = MEMORY_DIR / f"{user_id}.json"
    mem_file.write_text(
        json.dumps(memory, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

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
        save_memory(user_id, [])
        reply = "忘了，从零开始。"
        target = group_id if is_group else user_id
        send_qq_message(target, reply, "group" if is_group else "private")
        print(f"  百约 → {nickname}: {reply}", flush=True)
        return

    # 判断是不是百裏本人
    is_owner = (user_id == OWNER_QQ)

    # 加载记忆 + 构建对话
    memory = load_memory(user_id)
    system_prompt = get_system_prompt(is_owner, nickname)
    messages = [{"role": "system", "content": system_prompt}]
    for m in memory:
        messages.append(m)
    messages.append({"role": "user", "content": f"{nickname}: {user_msg}"})

    # 调 LLM
    reply = call_llm(messages)

    # 保存记忆（存 AI 原文，不含 CQ 码）
    memory.append({"role": "user", "content": user_msg})
    memory.append({"role": "assistant", "content": reply})
    save_memory(user_id, memory)

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

async def start_server():
    """启动 WebSocket 服务器"""
    print(f"\n  [服务器] 监听 ws://127.0.0.1:{BOT_PORT}")
    print(f"  [提示] 请确保 NapCat WebUI 已添加反向 WS → ws://127.0.0.1:{BOT_PORT}")
    print(f"  [提示] 如果 AstrBot 占用了同一个端口，先停掉它\n")

    async with websockets.serve(handle_ws, "127.0.0.1", BOT_PORT):
        await asyncio.Future()  # 永久运行

# ==================== 启动 ====================
def main():
    print("=" * 44)
    print("  百约 · BaiYue  v1.0")
    print("  「我是 AI，但我懂你」")
    print(f"  NapCat API: {NAPCAT_HTTP}")
    print("=" * 44)

    # 检查 NapCat
    try:
        r = requests.get(f"{NAPCAT_HTTP}/get_status", timeout=5)
        online = r.json().get("data", {}).get("online", False)
        if online:
            print("  [OK] NapCat 在线，QQ 已登录")
        else:
            print("  [警告] NapCat 运行中但 QQ 未登录")
    except:
        print("  [错误] 连不上 NapCat (端口3000)，请先启动 NapCatQQ")
        return

    # 检查 API Key
    if not DEEPSEEK_KEY:
        print("  [警告] 未设置 DEEPSEEK_KEY，百约会用默认回复")

    # 启动
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        print("\n  百约：下次见，拍档。")
    except OSError as e:
        if "address already in use" in str(e).lower() or "10048" in str(e):
            print(f"\n  [错误] 端口 {BOT_PORT} 被占用（可能是 AstrBot 在用）")
            print(f"  解决方法：停掉占用程序，或修改 BOT_PORT 换个端口")
        else:
            raise

if __name__ == "__main__":
    main()
