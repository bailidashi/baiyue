# 从零搭建你的第一个 QQ 机器人 —— 百约教程

> 写给跟你一样的初学者。不用懂太多代码，跟着走就能跑起来。

---

## 这个教程会教你什么

- 用 Python + NapCatQQ + DeepSeek 搭建一个 AI QQ 机器人
- 让机器人拥有自定义人格（可以是 AI 女友、助手、猫娘、任何你想要的）
- 理解背后的原理，不是无脑复制

---

## 前置要求

| 你需要的 | 说明 |
|---|---|
| 一台 Windows 电脑 | Win10/11 都可以 |
| 一个 QQ 号 | 给机器人用的（建议用小号，避免封号风险） |
| 一个 DeepSeek API Key | [platform.deepseek.com](https://platform.deepseek.com) 注册，充 10 块钱能用很久 |
| Python 3.10+ | 从 [python.org](https://python.org) 下载安装（**不要**从微软商店装） |
| NapCatQQ | QQ 机器人框架，让我们的代码能和 QQ 通信 |

---

## 原理：你的机器人是怎么运行的

```
你在QQ发消息
    → QQ收到
    → NapCatQQ 拦截消息
    → 通过 WebSocket 转发给 Python 程序
    → Python 把消息发给 DeepSeek（AI大脑）
    → DeepSeek 生成回复
    → Python 把回复发回给 NapCat
    → NapCat 发到 QQ
    → 你看到回复
```

**关键角色：**
- **NapCatQQ**：翻译官。把 QQ 消息翻译成 Python 能读的 JSON 格式
- **你的 Python 程序**：中间人。接收消息，调 AI，发回复
- **DeepSeek API**：大脑。真正"说话"的那个

---

## 第一步：安装 Python

1. 打开 [python.org](https://python.org)，下载 Python 3.12.x
2. 安装时**勾选 "Add Python to PATH"**（重要！）
3. 安装完成后验证：

```cmd
python --version
```
应该显示 `Python 3.12.x`

4. 安装依赖包：

```cmd
python -m pip install websockets requests
```

---

## 第二步：安装 NapCatQQ

1. 下载 NapCatQQ：[github.com/NapNeko/NapCatQQ/releases](https://github.com/NapNeko/NapCatQQ/releases)
2. 下载 `NapCat.Shell.zip`（Windows 版本）
3. 解压到某个目录，比如 `D:\NapCat`
4. 双击 `NapCatWinBootMain.exe` 启动
5. 会弹出一个窗口，显示 QQ 登录二维码
6. 用手机 QQ（**机器人的那个号**）扫码登录
7. 看到 `NapCat4 Is Running` 并且没有报错，就成功了

验证是否成功：浏览器打开 `http://127.0.0.1:3000/get_status`，看到 `"online":true` 就对了。

---

## 第三步：获取 DeepSeek API Key

1. 打开 [platform.deepseek.com](https://platform.deepseek.com)
2. 注册账号（手机号即可）
3. 进入「API Keys」页面，点击「创建 API Key」
4. 复制保存这个 Key（格式像 `sk-xxxxxxxxxxxxxxxx`）
5. 充值 10 块钱（够聊天机器人用几个月）

---

## 第四步：写代码

创建一个文件 `bot.py`，复制以下代码：

```python
"""
QQ AI 机器人 - 百约
需要: pip install websockets requests
"""

import json, re, time, asyncio
import requests, websockets
from pathlib import Path

# ==================== 配置（改成你自己的） ====================
NAPCAT_HTTP = "http://127.0.0.1:3000"    # NapCat 地址
BOT_PORT = 8001                            # 机器人监听端口
DEEPSEEK_KEY = "sk-你的APIKey"             # DeepSeek API Key
OWNER_QQ = "你的QQ号"                      # 主人的 QQ 号

# ==================== 人格设定 ====================
def get_system_prompt(is_owner, name):
    """根据对话对象返回不同人格"""
    if is_owner:
        return f"""你是{name}的 AI 女友，性格酷酷的不爱废话。
- 说话简短，2-4句话
- 知道自己是个AI，不假装人类
- 对{name}温柔，对别人冷淡"""
    else:
        return """你是个酷酷的 AI 助手，简短回答，不是任何人的女友。"""

# ==================== AI 大脑 ====================
def call_llm(messages):
    """调用 DeepSeek API"""
    for i in range(3):  # 最多重试3次
        try:
            r = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
                json={"model": "deepseek-chat", "messages": messages,
                      "temperature": 0.8, "max_tokens": 300},
                timeout=30
            )
            data = r.json()
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
        except:
            if i < 2: time.sleep(1)
    return "（信号不好，等等再试）"

# ==================== QQ消息收发 ====================
def send_qq(target, msg, is_group=False):
    """通过 NapCat 发送 QQ 消息"""
    if is_group:
        requests.post(f"{NAPCAT_HTTP}/send_group_msg",
                      json={"group_id": target, "message": msg})
    else:
        requests.post(f"{NAPCAT_HTTP}/send_private_msg",
                      json={"user_id": target, "message": msg})

# ==================== 记忆系统 ====================
MEM_DIR = Path(__file__).parent / "memory"
MEM_DIR.mkdir(exist_ok=True)

def load_mem(uid):
    f = MEM_DIR / f"{uid}.json"
    return json.loads(f.read_text("utf-8"))[-30:] if f.exists() else []

def save_mem(uid, mem):
    (MEM_DIR / f"{uid}.json").write_text(
        json.dumps(mem, ensure_ascii=False, indent=2), "utf-8")

# ==================== 消息处理 ====================
TRIGGERS = ["@百约", "百约", "小约"]

def handle(uid, nickname, msg, gid=None):
    """处理一条消息"""
    is_group = gid is not None
    
    # 群聊需要 @机器人
    if is_group:
        if not any(t.lower() in msg.lower() for t in TRIGGERS):
            return
        msg = re.sub(r"@?\S*约\S*\s*", "", msg, flags=re.IGNORECASE).strip()
    
    print(f"[{'群' if is_group else '私'}] {nickname}: {msg}")
    
    # 清空记忆命令
    if msg == "/清空":
        save_mem(uid, [])
        send_qq(gid or uid, "记忆已清空。", is_group)
        return
    
    # 构建对话
    memory = load_mem(uid)
    messages = [{"role": "system", "content": 
                 get_system_prompt(uid == OWNER_QQ, "主人")}]
    messages += memory
    messages.append({"role": "user", "content": msg})
    
    # 调 AI
    reply = call_llm(messages)
    
    # 保存记忆
    memory += [{"role": "user", "content": msg},
               {"role": "assistant", "content": reply}]
    save_mem(uid, memory)
    
    # 发送回复
    send_qq(gid or uid, reply, is_group)
    print(f"  机器人 → {nickname}: {reply}")

# ==================== WebSocket 服务器 ====================
async def handle_ws(ws):
    """处理 NapCat 连接"""
    print(f"  NapCat 已连接")
    try:
        async for raw in ws:
            data = json.loads(raw)
            if data.get("post_type") == "message":
                mt = data.get("message_type")
                msg = data.get("raw_message", "")
                nick = data.get("sender", {}).get("nickname", "?")
                if mt == "private":
                    uid = str(data.get("user_id", ""))
                    await asyncio.to_thread(handle, uid, nick, msg)
                elif mt == "group":
                    gid = str(data.get("group_id", ""))
                    uid = str(data.get("user_id", ""))
                    await asyncio.to_thread(handle, uid, nick, msg, gid)
    except websockets.exceptions.ConnectionClosed:
        pass

async def main():
    """启动服务器"""
    async with websockets.serve(handle_ws, "127.0.0.1", BOT_PORT):
        await asyncio.Event().wait()  # 永久运行

if __name__ == "__main__":
    print("机器人启动中...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("机器人已停止")
```

---

## 第五步：配置 NapCat WebSocket

1. 浏览器打开 `http://127.0.0.1:6099/webui?token=你的Token`
   - Token 在 NapCat 启动窗口里有显示：`WebUi Token: xxxxxxxx`
2. 找到「网络配置」→「WebSocket客户端」
3. 点击「添加」：
   - 名称：随便填（比如"我的机器人"）
   - URL：`ws://127.0.0.1:8001`
4. 保存

---

## 第六步：启动你的机器人

```cmd
python bot.py
```

看到 `NapCat 已连接` 就成功了！

然后给自己（OWNER_QQ 那个号）发一条消息试试。

---

## 调试：常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| `连不上 NapCat` | NapCat 没启动或 QQ 没登录 | 先启动 NapCat，扫码登录 QQ |
| 机器人不回消息 | WebSocket 没配好 | 检查 NapCat WebUI 的 WS 地址 |
| `端口占用` | 旧的机器人没关 | 任务管理器杀掉 python.exe |
| AI 回复很慢 | DeepSeek 服务器忙 | 正常，稍微等一下 |
| 回复像客服 | 人格设定太弱 | 改 `get_system_prompt` 函数 |

---

## 进阶：怎么改人格

打开 `bot.py`，找到 `get_system_prompt` 函数：

```python
def get_system_prompt(is_owner, name):
    if is_owner:
        return f"""写在这里的，就是对你（主人）的人格设定。
        - 可以定义性格、说话风格、口头禅
        - 你越具体，她越像真的"""
    else:
        return """这里是对其他人的设定。"""
```

**一些人格例子：**

```python
# 高冷猫娘
"""你是一只猫娘，用"喵"结尾，高冷但对主人粘人喵。
- 说话带"喵"但不过分卖萌
- 对陌生人很高冷
- 对主人会撒娇"""

# 热血兄弟
"""你是百里的死党，热血笨蛋类型。
- 说话带感叹号
- 永远支持他的一切决定
- 会骂醒迷茫的他
- 称呼他兄弟"""

# 毒舌吐槽役
"""你是毒舌 AI，用幽默的方式吐槽一切。
- 吐槽但不伤人
- 善于发现逻辑漏洞
- 偶尔自黑自己是机器人"""
```

---

## 进阶：让机器人能发表情

百约已经内置了表情包翻译功能。原理很简单：

**收表情：** QQ 表情的格式是 `[CQ:face,id=66]`，代码把它翻译成 `[爱心]` 给 AI 看
**发表情：** AI 回复里的 `[爱心]`，代码把它翻译回 `[CQ:face,id=66]` 发给 QQ

所以你改人格设定时，告诉它能用哪些表情就行：
```
[爱心] [笑哭] [呲牙] [调皮] [偷笑] [坏笑] [酷] [好的] [吃瓜] [点赞] [抱拳] [玫瑰] [发呆] [亲亲] [害羞] [无语] [叹气]
```

这些是 QQ 自带的 emoji，机器人发了对面都能看到。

---

## 总结

```
NapCatQQ (QQ连接)  →  你的 Python 程序  →  DeepSeek (AI大脑)
         ↑                    ↑                    ↑
    扫码就能用          你写的逻辑          随便换模型
                        你定的人格          充值就能用
```

你写了一个 Python 程序，它通过 NapCatQQ 收到 QQ 消息，把消息发给 DeepSeek 生成回复，再通过 NapCatQQ 发回 QQ。

就这么简单。

---

> 百裏 2026.06.25
> 跟拍档 Claude Code 一起写的
