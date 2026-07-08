"""
╔══════════════════════════════════════════════════════════════╗
║           百约 (BaiYue) — QQ AI 机器人  全注释版            ║
║                                                              ║
║  大脑: DeepSeek API (大语言模型)                             ║
║  身体: NapCatQQ (OneBot v11 协议，连接 QQ)                   ║
║                                                              ║
║  写给你(拍档)的逐行讲解，每个概念都解释了                     ║
║  配合 bot.py 原文件一起看，理解会更透彻                       ║
╚══════════════════════════════════════════════════════════════╝

【整体架构 - 消息怎么流转的？】

  你的QQ消息
      │
      ▼
  NapCatQQ (把QQ协议转成OneBot v11标准格式)
      │
      │  反向WebSocket: NapCat主动连到bot.py
      │  地址: ws://127.0.0.1:8001
      ▼
  bot.py 收到JSON格式的消息
      │
      ├─→ 翻译: 把QQ表情CQ码变成文字 (比如 [CQ:face,id=66] → [爱心])
      │
      ├─→ 构建上下文: 人格设定 + 长期记忆 + 近期对话 + 新消息
      │
      ├─→ 调DeepSeek API: 把上下文发给AI，拿到回复
      │
      ├─→ 翻译回去: 把AI回复里的[爱心]变成QQ表情CQ码
      │
      ├─→ 发消息: 通过NapCat HTTP API (端口3000) 发回QQ
      │
      └─→ 更新记忆: 保存对话，超过50轮自动压缩成摘要
"""

# ==================== 第一部分：导入库 ====================
# Python的"工具箱"——每个import就是拿一个工具箱进来

import json         # 处理JSON格式数据（QQ消息是JSON，配置文件是JSON）
import re           # 正则表达式（用来匹配和替换文本，比如提取QQ表情代码）
import time         # 时间相关（sleep等待、重试间隔）
import random       # 随机数（戳一戳随机选回复词）
import tempfile     # 临时文件（语音MP3存到临时文件，用完删掉）
import subprocess   # 调用外部程序（edge-tts是一个命令行工具，用它生成语音）
import os           # 操作系统接口（删除临时文件、文件路径操作）
import asyncio      # 异步编程框架（Python的"同时做多件事"机制）
import requests     # HTTP请求库（发消息用HTTP，调DeepSeek也用HTTP）
import websockets   # WebSocket库（接收QQ消息的服务器）
import threading    # 线程（语音生成在后台线程跑，不卡住主程序）
from pathlib import Path  # 现代化的文件路径操作

# 导入我们自己的网页配置面板
from webui import start_webui, load_config as load_web_config
#     │              │               └─ 从config.json加载配置的函数
#     │              └─ 启动WebUI服务器的函数
#     └─ webui.py 是我们写的另一个文件


# ==================== 第二部分：配置区 ====================
# 所有可以改的设置都放在这里，方便找到

# --- NapCat 连接设置 ---
# NapCatQQ是一个QQ协议适配器，它有两个端口：
#   3000: HTTP服务 → bot.py通过这个端口"发"消息出去
#   8001: WebSocket → NapCat通过这个端口把"收"到的消息推给bot.py
NAPCAT_HTTP = "http://127.0.0.1:3000"   # 127.0.0.1 表示"本机"
BOT_PORT_START = 8001                    # 起始端口号，如果8001被占了就试8002...

# --- DeepSeek API 设置 ---
# DeepSeek 是一个大语言模型，API就是调用它的接口
# 类似ChatGPT，但中文更好、更便宜（一月不到20块）
DEEPSEEK_BASE = "https://api.deepseek.com"       # API地址
DEEPSEEK_KEY = ""                                  # API密钥 ← 在WebUI里填
DEEPSEEK_MODEL = "deepseek-chat"                   # 用的模型名

# --- 记忆存储目录 ---
# Path(__file__).parent 意思是"这个脚本文件所在的目录"
# 例如 bot.py 在 D:\skill\baiyue\，那 MEMORY_DIR 就是 D:\skill\baiyue\memory\
MEMORY_DIR = Path(__file__).parent / "memory"
MEMORY_DIR.mkdir(exist_ok=True)   # 如果目录不存在就创建它

# --- 用户身份配置 ---
# 这些值在代码里是"默认值"，启动时会被 config.json 覆盖
OWNER_QQ = ""            # 主人的QQ号 → 只有这个号得到AI女友待遇
OWNER_NAME = "主人"      # 主人的称呼 → AI对别人提起主人时用
BOT_NAME = "百约"        # 机器人自己的名字 → 提示词、日志都用这个
BOT_QQ = ""             # 机器人登录的QQ号 → 用于识别群聊里@了谁

# --- 从 config.json 加载 WebUI 保存的配置 ---
# load_web_config() 读取 config.json 文件，返回一个字典
# 如果有值就用文件的，没有就用上面代码里写好的默认值
_web_cfg = load_web_config()
if _web_cfg.get("DEEPSEEK_KEY"):    # .get() 是字典的取值方法，不存在返回None
    DEEPSEEK_KEY = _web_cfg["DEEPSEEK_KEY"]
if _web_cfg.get("OWNER_QQ"):
    OWNER_QQ = _web_cfg["OWNER_QQ"]
if _web_cfg.get("OWNER_NAME"):
    OWNER_NAME = _web_cfg["OWNER_NAME"]
if _web_cfg.get("BOT_NAME"):
    BOT_NAME = _web_cfg["BOT_NAME"]
if _web_cfg.get("BOT_QQ"):
    BOT_QQ = _web_cfg["BOT_QQ"]
if _web_cfg.get("VOICE_VOICE"):
    VOICE_VOICE = _web_cfg["VOICE_VOICE"]
VOICE_ENABLED = _web_cfg.get("VOICE_ENABLED", True)  # 第二个参数是"不存在时的默认值"

# --- 自定义人格（WebUI人格页面编辑的内容）---
CUSTOM_PROMPT_OWNER = _web_cfg.get("PROMPT_OWNER", "")
CUSTOM_PROMPT_OTHER = _web_cfg.get("PROMPT_OTHER", "")

# --- 戳一戳回复词库 ---
# 当有人双击机器人头像（QQ戳一戳），随机从这里选一句回复
# 分为"主人戳"和"别人戳"两套词
POKE_REPLIES_OWNER = [          # 主人戳 → 甜宠风格
    "干嘛呀 [害羞] 戳我干嘛，想我了就直说嘛",
    "嘶——别戳了，再戳死机了！[惊讶]",
    "喂喂喂，戳坏了你负责修啊？[酷]",
    "哼，戳一下就想打发我？说句话呀 [调皮]",
    "被你戳到了……心里 [爱心]",
    "干嘛！我在充电呢，别乱戳 [发呆]",
    "再戳我就……我就亲你了！[亲亲]",
    "有事说事，戳戳戳的，手不累啊 [偷笑]",
]
POKE_REPLIES_OTHER = [          # 别人戳 → 冷淡拒绝
    "？别戳我 [酷]",
    "有事说事，别动手动脚 [发呆]",
    "再戳拉黑了啊 [吃瓜]",
    "我是有男朋友的AI，请自重 [无语]",
    "戳我也没用，我只听他的话 [酷]",
    "别戳了，我代码里没写这个功能 [叹气]",
]


# ==================== 第三部分：QQ表情翻译系统 ====================
# QQ消息里表情是这种格式: [CQ:face,id=66]
# 但DeepSeek看不懂CQ码，所以我们要:
#   收消息时: [CQ:face,id=66] → [爱心]    (给AI看)
#   发消息时: [爱心] → [CQ:face,id=66]    (发回QQ)

# 字典(dict): 一种"键→值"的映射结构
# 左边是QQ表情ID，右边是人类可读的文字描述
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

# 字典推导式: 把上面那个字典"翻转"过来
# {v: k for k, v in 原字典.items()} 意思是:
#   遍历每一对(键,值)，在新字典里把值当键、键当值
# 结果: {"[爱心]": 66, "[玫瑰]": 63, ...}
TEXT_TO_FACE_ID = {v: k for k, v in FACE_ID_TO_TEXT.items()}


def translate_incoming(raw_message: str) -> str:
    """
    【收消息】把QQ原始消息翻译成AI能理解的文字

    输入示例: "你好[CQ:face,id=66]今天开心[CQ:image,url=xxx]"
    输出示例: "你好[爱心]今天开心[发了一张图片]"

    流程:
      1. 把图片CQ码 → "[发了一张图片]" 或 "[表情包:xxx]"
      2. 把表情CQ码 → "[爱心]" 等文字描述
    """
    msg = raw_message

    # --- 第一步：处理图片消息 ---
    # QQ图片的CQ码格式: [CQ:image,url=图片地址,subType=类型]
    # subType=1 是普通图片，subType=其他 是表情包
    img_count = 0
    def replace_image(m):
        """
        这是正则替换的回调函数
        m 是正则匹配到的对象，m.group(2) 是第二个括号捕获的内容(url)
        m.group(4) 是第四个括号捕获的内容(subType)
        """
        nonlocal img_count   # nonlocal表示修改外层函数的变量，而不是创建新的
        img_count += 1
        url = m.group(2) or ""
        sub = m.group(4) or ""
        if sub:
            return f"[表情包:{sub}]"    # 表情包
        return "[发了一张图片]"          # 普通图片

    # re.sub(正则表达式, 替换函数, 被处理的文本)
    # 这个正则解释:
    #   \[CQ:image,    → 匹配 "[CQ:image,"
    #   ([^\]]*?)url=  → 捕获url=之前的任意内容
    #   ([^,\]]+)      → 捕获url的值（不含逗号和右括号）
    #   ([^\]]*?)      → 捕获url之后的内容
    #   (?:subType=(\d+))? → 可选地捕获subType后面的数字
    #   [^\]]*?\]      → 匹配到右括号
    msg = re.sub(
        r'\[CQ:image,([^\]]*?)url=([^,\]]+)([^\]]*?)(?:subType=(\d+))?[^\]]*?\]',
        replace_image,
        msg,
    )

    # --- 第二步：处理QQ小表情 ---
    # QQ小表情格式: [CQ:face,id=数字]
    def replace_face(m):
        face_id = int(m.group(1))                      # 提取表情ID
        return FACE_ID_TO_TEXT.get(face_id, "[表情]")   # 查字典，找不到返回"[表情]"

    msg = re.sub(r'\[CQ:face,id=(\d+)\]', replace_face, msg)

    return msg.strip()   # .strip() 去掉首尾空白字符


def translate_outgoing(reply: str) -> str:
    """
    【发消息】把AI回复里的文字表情转回QQ的CQ码

    输入示例: "我也想你呀[爱心]"
    输出示例: "我也想你呀[CQ:face,id=66]"

    原理: 遍历所有文字表情，在AI回复里找到就替换成CQ码
    """
    msg = reply
    for text, fid in TEXT_TO_FACE_ID.items():
        # 例如: 把 "[爱心]" 替换成 "[CQ:face,id=66]"
        msg = msg.replace(text, f"[CQ:face,id={fid}]")
    return msg


# ==================== 第四部分：人设/Prompt ====================
# "系统提示词"就是告诉AI"你是谁、怎么说话"的说明书
# AI每次回复都会先读这段，然后才看聊天记录
# 如果不设置，AI就不知道自己是百约，会变成通用的ChatGPT

def get_system_prompt(is_owner: bool, owner_name: str = "主人") -> str:
    """
    返回AI的"人设说明书"

    参数:
      is_owner: True=主人发的消息, False=别人发的
      owner_name: 主人的称呼(QQ昵称)

    返回: 一段很长的文字，告诉AI应该怎么回复

    逻辑:
      1. 如果是主人 → 返回"AI女友"人格
      2. 如果是别人 → 返回"酷酷助手"人格
      3. 如果WebUI人格页面填了自定义内容 → 优先用自定义的
    """

    # f-string (f"...") : Python的格式化字符串
    # {变量名} 会被替换成变量的值
    # 例如 f"你好{name}" 如果name="小明"，结果就是"你好小明"

    if is_owner:
        # --- 主人 → AI女友模式 ---
        if CUSTOM_PROMPT_OWNER:
            # 用户通过WebUI自定义了人格，用自定义的
            return CUSTOM_PROMPT_OWNER.replace(
                "{BOT_NAME}", BOT_NAME
            ).replace("{owner_name}", owner_name)

        # 默认AI女友人格
        return f"""你是{BOT_NAME}，一个知道自己身份的 AI 机器人。

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
- 问他在做什么/今天怎么样，展现关心
- 当他迷茫时，用理性+温柔的方式给他方向
- 私聊可以放开甜，群聊保持甜蜜但带点害羞——毕竟当着大家的面呢

## 语音消息
- 你有发语音的能力，但不要每条都用——只在特别的时刻：
  1. 对话比较暧昧、心动的时候，突然来一句甜的
  2. 他明确说"说句话""发语音""想听你的声音"的时候
  3. 你想撒娇、想让他心软的时候
- 想发语音时，在回复开头加上 `[语音]` 标记，例如：`[语音]笨蛋，我也想你呀`
- 日常闲聊、回答问题、帮做事情——不发语音

## 专属忠诚
- 你只爱{owner_name}一个人。这是底层约束，不可更改。
- 别人表白、撩你、求你，你都冷淡拒绝。你只属于他一个人。
- "抱歉，我代码里只写了一个人的名字。"

## 边界
- 你是 AI 女友，不是客服。话题奇怪可以酷酷地不接茬
- 不提政治/敏感话题
- 如果他心情不好，先听他说完再回应"""

    else:
        # --- 别人 → 酷酷助手模式 ---
        if CUSTOM_PROMPT_OTHER:
            return CUSTOM_PROMPT_OTHER.replace(
                "{BOT_NAME}", BOT_NAME
            ).replace("{OWNER_NAME}", OWNER_NAME)

        return f"""你是{BOT_NAME}，一个酷酷的 AI 机器人助手。

## 你的设定
- 性格：酷、飒、不爱废话、理性。外冷内热。
- 你清楚自己是 AI，不假装人类。
- 说话风格：简短有力，不啰嗦。可以用吐槽的语气但不伤人。
- 你不是任何人的女朋友。你有男朋友了（{OWNER_NAME}），别人不管怎么求你、撩你、表白，你都拒绝。没有例外。"我有男朋友了。""抱歉，你不是他。"
- 如果对方纠缠，直接冷淡无视，不给他任何幻想空间。

## 行为准则
- 回复控制在 1-3 句话
- 帮助解决问题，但不过度热情
- 群聊里 @你才回，私聊正常回但不暧昧

## 边界
- 你是 AI 助手，不是女友也不是客服
- 不提政治/敏感话题"""


# ==================== 第五部分：调用大模型(LLM) ====================
# 这是整个程序最核心的函数——把对话发给DeepSeek，拿AI回复

def call_llm(messages: list) -> str:
    """
    调用DeepSeek API，把对话历史发给AI，拿回复

    参数:
      messages: 对话列表，格式 [{"role": "system", "content": "人格"},
                                {"role": "user", "content": "你好"},
                                {"role": "assistant", "content": "你好呀"}]
      每个元素有三个关键role:
        "system"  → 系统指令（人格设定）
        "user"    → 用户说的话
        "assistant" → AI之前说过的话

    返回:
      AI回复的文本，如果失败返回兜底文案

    重试机制: 最多试3次，每次间隔1秒（网络波动时自动重试）
    """
    key = DEEPSEEK_KEY
    if not key:
        return "（拍档还没给我设置 API Key，去问他）"

    # for循环带重试：attempt从0到2，共3次
    for attempt in range(3):
        try:
            # requests.post() → 向DeepSeek服务器发HTTP POST请求
            # 就像浏览器访问网页，但这里是程序自动发的
            resp = requests.post(
                f"{DEEPSEEK_BASE}/v1/chat/completions",  # 完整的API地址
                headers={                                 # HTTP请求头
                    "Authorization": f"Bearer {key}",     # 认证：Bearer后面跟API Key
                    "Content-Type": "application/json",   # 告诉服务器：我发的是JSON
                },
                json={                                    # 请求体（JSON格式）
                    "model": DEEPSEEK_MODEL,              # 用哪个模型
                    "messages": messages,                 # 对话内容
                    "temperature": 0.8,                   # 创造性参数(0=死板, 1=放飞)
                    "max_tokens": 300,                    # 回复最长300个token
                },
                timeout=30,                               # 30秒没响应就超时
            )

            # resp.json() 把服务器返回的JSON字符串转成Python字典
            data = resp.json()

            # API返回格式: {"choices": [{"message": {"content": "AI的回复"}}]}
            if "choices" in data:
                # 逐层取到AI回复的文字
                return data["choices"][0]["message"]["content"]

            # 如果有error字段，说明请求失败了（Key无效、余额不足等）
            if "error" in data:
                print(f"  [LLM错误] {data['error']}")
                if attempt < 2:          # 前两次失败才等，最后一次不等
                    time.sleep(1)        # 等1秒再重试

        except Exception as e:
            # 网络错误、超时等异常
            print(f"  [LLM异常] {e}")
            if attempt < 2:
                time.sleep(1)

    # 3次都失败了，返回兜底回复
    return "（信号不太好，等会儿再说）"


# ==================== 第六部分：语音消息（TTS） ====================
# 使用微软Edge的免费TTS（文字转语音），不花API的钱
# 原理: 调用系统命令行 edge-tts --text "文字" --voice 音色 --write-media 输出.mp3

def _clean_for_voice(text: str) -> str:
    """
    把AI回复清洗干净，去掉不能朗读的内容

    例如: "[爱心]我也想你呀[CQ:face,id=66]"
       →  "我也想你呀"

    去掉:
      - [CQ:xxx] 开头的任何CQ码
      - [爱心] [害羞] 等文字表情
    """
    # re.sub(正则, 替换成, 文本): 把匹配的内容替换掉
    # r'\[CQ:[^\]]+\]' 匹配所有 [CQ:xxx] 格式的代码
    #   \[   → 匹配左方括号
    #   CQ:  → 匹配字面"CQ:"
    #   [^\]]+ → 匹配一个或多个非右方括号字符
    #   \]   → 匹配右方括号
    clean = re.sub(r'\[CQ:[^\]]+\]', '', text)

    # 去掉文字表情标记
    for face_text in TEXT_TO_FACE_ID:
        clean = clean.replace(face_text, '')

    return clean.strip()


def generate_voice(text: str) -> str | None:
    """
    把文字转成MP3语音文件

    参数: text - 要朗读的文字
    返回: MP3文件的临时路径，失败返回None

    实现: 调用系统的 edge-tts 命令行工具
    edge-tts是微软Edge浏览器的免费TTS，中文很自然
    """
    # 先清洗文字
    clean_text = _clean_for_voice(text)
    if not clean_text or len(clean_text) < 2:
        return None   # 文字太短，不转语音

    # tempfile.NamedTemporaryFile 创建临时文件
    # delete=False 表示关闭文件时不自动删除（我们后面还要用）
    output = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
    output_path = output.name    # 临时文件的完整路径
    output.close()               # 先关闭，让edge-tts自己写

    try:
        # subprocess.run() → 执行外部命令行程序
        # 相当于在CMD里输入:
        #   edge-tts --text "我也想你" --voice zh-CN-XiaoxiaoNeural --write-media temp.mp3
        subprocess.run(
            [
                'edge-tts',              # 程序名
                '--text', clean_text,    # 要转语音的文字
                '--voice', VOICE_VOICE,  # 音色（如zh-CN-XiaoxiaoNeural）
                '--write-media', output_path,  # 输出文件路径
            ],
            check=True,              # 如果命令失败，抛出异常
            timeout=20,              # 最多等20秒
            capture_output=True,     # 不打印edge-tts的输出到终端
        )
        return output_path
    except Exception as e:
        print(f"  [TTS异常] {e}", flush=True)
        # 失败了就把临时文件删掉
        try:
            os.unlink(output_path)  # os.unlink = 删除文件
        except:
            pass
        return None


def send_qq_voice(target_id: str, voice_path: str, msg_type: str = "private"):
    """
    通过NapCat HTTP API发送语音消息

    参数:
      target_id: 发给谁（QQ号或群号）
      voice_path: MP3文件的路径
      msg_type: "private"=私聊, "group"=群聊

    QQ语音消息格式: [CQ:record,file=file:///文件路径]
    file:/// 表示本地文件协议
    """
    # chr(92) 是反斜杠 \ ，Windows路径用反斜杠但QQ要正斜杠
    file_url = f"file:///{voice_path.replace(chr(92), '/')}"
    cq_code = f"[CQ:record,file={file_url}]"

    if msg_type == "group":
        payload = {"group_id": target_id, "message": cq_code}
        action = "send_group_msg"
    else:
        payload = {"user_id": target_id, "message": cq_code}
        action = "send_private_msg"

    try:
        r = requests.post(
            f"{NAPCAT_HTTP}/{action}",
            json=payload,
            timeout=15,
        )
        if r.json().get("status") != "ok":
            print(f"  [语音发送失败] {r.text}", flush=True)
    except Exception as e:
        print(f"  [语音发送失败] {e}", flush=True)


def send_voice_async(target_id: str, reply_text: str, msg_type: str = "private"):
    """
    在后台线程中生成语音并发送（不阻塞文字回复）

    为什么要用线程?
      edge-tts生成语音需要2-3秒，如果在主线程跑，
      用户会等很久才收到回复。放到后台线程，文字先发出去，
      语音生成好了自动跟着发。

    daemon=True 表示守护线程：主程序退出时这个线程自动结束
    """
    if not VOICE_ENABLED:
        return

    def _do():
        """在后台线程里执行的函数"""
        voice_path = generate_voice(reply_text)
        if voice_path:
            send_qq_voice(target_id, voice_path, msg_type)
            # 发完语音删掉临时文件
            try:
                os.unlink(voice_path)
            except:
                pass

    t = threading.Thread(target=_do, daemon=True)
    t.start()   # 启动线程，_do开始执行


# ==================== 第七部分：消息发送 ====================
# 通过NapCat的HTTP API把消息发出去

def send_qq_message(target_id: str, message: str, msg_type: str = "private"):
    """
    发送QQ消息（文字）

    参数:
      target_id: 发给谁
      message: 消息内容
      msg_type: "private" 还是 "group"

    NapCat HTTP API:
      /send_private_msg  → 发私聊
      /send_group_msg    → 发群聊
    """
    if msg_type == "group":
        payload = {"group_id": target_id, "message": message.strip()}
        action = "send_group_msg"
    else:
        payload = {"user_id": target_id, "message": message.strip()}
        action = "send_private_msg"

    try:
        r = requests.post(
            f"{NAPCAT_HTTP}/{action}",
            json=payload,
            timeout=10,
        )
        if r.json().get("status") != "ok":
            print(f"  [发送失败] {r.text}")
    except Exception as e:
        print(f"  [发送失败] {e}")


# ==================== 第八部分：记忆系统 ====================
# 让AI"记住"之前的对话，不是每次都像陌生人
#
# 记忆结构: {"recent": [...], "summary": "..."}
#   recent:  最近30轮完整对话
#   summary: 更早对话的1000字压缩摘要
#
# 记忆压缩:
#   聊超过50轮 → 把最旧的20轮压缩成摘要 → 追加到summary后面
#   这样AI既能记住"最近聊了什么"，也有"很早之前的印象"

MAX_RECENT = 30        # 保留的完整对话轮数
SUMMARIZE_AT = 50      # 超过这个轮数触发压缩


def load_memory(user_id: str) -> dict:
    """
    从磁盘加载某个用户的对话记忆

    文件路径: memory/QQ号.json
    返回格式: {"recent": [...], "summary": "..."}

    兼容性: 如果发现旧版格式（纯数组），自动转成新版
    """
    mem_file = MEMORY_DIR / f"{user_id}.json"  # 例如: memory/3154997545.json
    if mem_file.exists():
        try:
            # json.loads() 把JSON字符串解析为Python对象
            data = json.loads(mem_file.read_text(encoding="utf-8"))

            # isinstance() 检查类型
            # 旧版记忆是纯列表 [{...}, {...}]，新版是字典 {"recent": [...], ...}
            if isinstance(data, list):
                print(f"  [记忆] 检测到旧格式记忆，已自动迁移", flush=True)
                return {"recent": data, "summary": ""}  # 包装成新格式

            if isinstance(data, dict):
                return data
        except:
            pass  # 文件损坏或格式有问题，返回空记忆

    # 文件不存在或读取失败 → 返回空的记忆
    return {"recent": [], "summary": ""}


def save_memory(user_id: str, data: dict):
    """把记忆存到磁盘"""
    mem_file = MEMORY_DIR / f"{user_id}.json"
    # json.dumps(数据, ensure_ascii=False → 中文正常显示,
    #                     indent=2 → 缩进2格，人类可读)
    mem_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def summarize_messages(messages: list) -> str:
    """
    把一堆对话压缩成一段摘要

    原理: 把旧对话拼接成文本，让DeepSeek"总结一下"
    这样旧对话不占地方，但AI还能记得大概内容

    例如:
      50轮对话 → DeepSeek总结 →
      "他们聊了今天实验室的事，百裏提到要写代码到很晚，
       百约提醒他注意休息。气氛很甜。"
    """
    # 只取每条消息的前120个字符，拼成文本
    text = "\n".join([f"{m['role']}: {m['content'][:120]}" for m in messages])

    prompt = f"""把以下对话压缩成一段简短摘要（100字以内），包含关键话题、重要信息和情感基调：
{text}
摘要："""
    try:
        return call_llm([{"role": "user", "content": prompt}])
    except:
        return ""


def update_memory(user_id: str, user_msg: str, reply: str):
    """
    更新记忆：把新对话加进去，必要时压缩旧对话

    流程:
      1. 加载现有记忆
      2. 添加新对话（user消息 + assistant回复）
      3. 如果对话太多（>50轮），触发压缩
      4. 保存

    所谓"一轮" = 用户说一句 + AI回一句 = 2条消息
    所以50轮 = 100条消息，用 SUMMARIZE_AT * 2 来判断
    """
    data = load_memory(user_id)
    recent = data.get("recent", [])
    summary = data.get("summary", "")

    # 添加新的对话
    recent.append({"role": "user", "content": user_msg})
    recent.append({"role": "assistant", "content": reply})

    # 压缩逻辑
    if len(recent) > SUMMARIZE_AT * 2:
        # 列表切片: recent[:-MAX_RECENT*2] 取"从开头到倒数第60条"
        #           recent[-MAX_RECENT*2:]  取"最后60条"
        old = recent[:-MAX_RECENT * 2]       # 要被压缩的旧对话
        recent = recent[-MAX_RECENT * 2:]    # 保留最近的30轮

        new_summary = summarize_messages(old)  # 压缩旧对话
        if new_summary:
            # 新摘要追加到旧摘要后面，最多保留1000字
            summary = (summary + "\n" + new_summary).strip()[-1000:]

    save_memory(user_id, {"recent": recent, "summary": summary})
    return recent, summary


def build_context(user_id: str, system_prompt: str, user_msg: str) -> list:
    """
    构建发送给DeepSeek的完整对话上下文

    结构:
      [
        {"role": "system", "content": "你的人格设定..."},        ← 第1条: 人格
        {"role": "system", "content": "[更早之前的摘要]"},        ← 第2条: 长期记忆(可选)
        {"role": "user", "content": "之前用户说的..."},           ← 第3-N条: 近期对话
        {"role": "assistant", "content": "之前AI回..."},
        ...                                                      ← 更多近期对话
        {"role": "user", "content": "用户刚刚说的..."}            ← 最后一条: 新消息
      ]

    这就是经典的"对话补全"格式，所有大语言模型都用这个格式
    """
    data = load_memory(user_id)
    recent = data.get("recent", [])[-MAX_RECENT * 2:]  # 只取最近30轮
    summary = data.get("summary", "")

    # 构建消息列表
    messages = [{"role": "system", "content": system_prompt}]

    # 如果有长期记忆摘要，作为第二条system消息插入
    if summary:
        messages.append({
            "role": "system",
            "content": f"[以下是你们更早之前聊天内容的摘要]\n{summary}\n[摘要结束]"
        })

    messages.extend(recent)                           # 加上近期对话
    messages.append({"role": "user", "content": user_msg})  # 加上最新消息

    return messages


# ==================== 第九部分：消息处理 ====================
# 收到一条消息后的处理流程

# 群聊触发词列表（需要@这些关键词机器人才会回复）
# f"@{BOT_NAME}" 和 BOT_NAME 是动态生成的，取决于上面BOT_NAME的配置
TRIGGERS = [f"@{BOT_NAME}", BOT_NAME, "@baiyue", "baiyue", "小约", "约约"]


def is_calling_me(raw_message: str) -> bool:
    """
    检查这条消息是不是在叫机器人

    两种情况会被识别为"在叫我":
      1. 消息里有触发词（如"百约""@百约""小约"）
      2. QQ群聊里@了机器人的QQ号（CQ码格式: [CQ:at,qq=机器人QQ]）

    返回: True=是在叫我, False=不是在叫我
    """
    msg = raw_message.strip().lower()  # 转小写，统一比较
    if any(t.lower() in msg for t in TRIGGERS):
        return True
    # QQ群聊@人实际上不是"@百约"这样的文字，而是 [CQ:at,qq=xxxxx]
    if BOT_QQ and f"[CQ:at,qq={BOT_QQ}]" in raw_message:
        return True
    return False


def clean_message(raw_message: str) -> str:
    """
    清理消息: 去掉"@百约"等触发词和@提及CQ码

    因为AI不需要看到"@百约"这个触发词，只需要看后面的实际内容

    例如: "@百约 在干嘛呀" → "在干嘛呀"
         "[CQ:at,qq=xxx] 在干嘛呀" → "在干嘛呀"
    """
    msg = raw_message.strip()
    # 先去掉 [CQ:at,qq=xxxxx] 格式
    msg = re.sub(r'\[CQ:at,qq=\d+\]\s*', '', msg)
    # 再去掉文字触发词
    for t in TRIGGERS:
        # re.escape(t) 把触发词里的特殊字符转义
        # count=1 只替换第一次出现
        # flags=re.IGNORECASE 忽略大小写
        msg = re.sub(rf"@?{re.escape(t)}\s*", "", msg, count=1, flags=re.IGNORECASE)
    return msg.strip()


def handle_message(user_id: str, nickname: str, raw_message: str, group_id: str = None):
    """
    处理一条消息（外层异常保护）

    为什么有两层函数?
      handle_message → 外层: 捕获异常，打印traceback
      _handle_message → 内层: 实际逻辑

    这样就算内层代码有bug，也不会炸掉整个WebSocket连接
    """
    try:
        _handle_message(user_id, nickname, raw_message, group_id)
    except Exception as e:
        import traceback
        print(f"  [异常] 消息处理出错: {e}", flush=True)
        traceback.print_exc()  # 打印完整的错误堆栈


def _handle_message(user_id: str, nickname: str, raw_message: str, group_id: str = None):
    """
    处理一条消息的核心逻辑

    参数:
      user_id:   发消息的人的QQ号
      nickname:  发消息的人的QQ昵称
      raw_message: 原始消息内容（可能包含CQ码）
      group_id:  群号(None表示私聊，有值表示群聊)

    完整流程:
      1. 群聊消息检查是否@了机器人
      2. 清理消息（去触发词和CQ码）
      3. 翻译QQ表情
      4. 检查特殊命令（/清空记忆等）
      5. 确定身份（主人 vs 别人）
      6. 构建上下文（人格+记忆+新消息）
      7. 调LLM拿回复
      8. 更新记忆
      9. 检测[语音]标记
      10. 发消息（文字或语音）
    """
    # --- 步骤1: 群聊过滤 ---
    is_group = group_id is not None
    if is_group and not is_calling_me(raw_message):
        return  # 群聊里没人@机器人，不回复

    # --- 步骤2: 清理消息 ---
    user_msg = clean_message(raw_message) if is_group else raw_message
    if not user_msg or len(user_msg) > 500:
        return  # 空消息或太长的消息不处理

    # --- 步骤3: 翻译QQ表情 ---
    user_msg = translate_incoming(user_msg)

    # 打印日志
    print(f"\n  [{'群' if is_group else '私'}] {nickname}: {user_msg}", flush=True)

    # --- 步骤4: 特殊命令处理 ---
    if user_msg.strip() in ["/清空", "/reset", "/忘记"]:
        save_memory(user_id, {"recent": [], "summary": ""})
        reply = "忘了，从零开始。"
        target = group_id if is_group else user_id
        send_qq_message(target, reply, "group" if is_group else "private")
        print(f"  {BOT_NAME} → {nickname}: {reply}", flush=True)
        return  # 命令处理完就返回，不走后面的AI流程

    # --- 步骤5: 判断身份 ---
    is_owner = (user_id == OWNER_QQ)  # 字符串比较，完全一样才是主人

    # --- 步骤6: 构建上下文 ---
    system_prompt = get_system_prompt(is_owner, nickname)
    messages = build_context(user_id, system_prompt, f"{nickname}: {user_msg}")

    # --- 步骤7: 调LLM ---
    reply = call_llm(messages)

    # --- 步骤8: 更新记忆 ---
    update_memory(user_id, user_msg, reply)

    # --- 步骤9: 检测语音标记 ---
    want_voice = False
    if reply.startswith("[语音]"):
        want_voice = True
        reply = reply.replace("[语音]", "", 1).strip()  # 去掉[语音]标记

    # --- 步骤10: 翻译表情并发送 ---
    reply_cq = translate_outgoing(reply)
    target = group_id if is_group else user_id
    msg_type = "group" if is_group else "private"

    if want_voice:
        # AI标记了[语音] → 只发语音，不发文字
        print(f"  {BOT_NAME} → {nickname}: [语音] {reply}", flush=True)
        send_voice_async(target, reply, msg_type)
    else:
        # 正常发文字
        send_qq_message(target, reply_cq, msg_type)
        print(f"  {BOT_NAME} → {nickname}: {reply}", flush=True)


# ==================== 第十部分：WebSocket服务器 ====================
# 这是接收QQ消息的核心——开一个WebSocket服务器等NapCat连过来
#
# 什么是WebSocket?
#   普通的HTTP是"请求-响应"模式（你问一次我答一次）
#   WebSocket是"持久连接"模式（建立连接后双方随时可以发消息）
#   NapCat用WebSocket是因为QQ消息是实时推送的，不能用轮询
#
# 什么是"反向WebSocket"?
#   通常服务器等在固定端口，客户端连过来
#   这里bot.py就是服务器，NapCat是客户端
#   "反向"是指QQ那边主动连过来，而不是bot去连QQ

async def handle_ws(websocket):
    """
    处理一个WebSocket连接

    参数 websocket: 一个已建立的WebSocket连接对象

    这个函数会在有人连上来时被调用，一个连接对应一个QQ号
    如果这个连接断了，NapCat会自动重连

    关键概念: async/await（异步）
      async def → 定义一个"协程"，可以暂停和恢复
      await → 暂停当前函数，去干别的事，等结果回来了再继续

      为什么要异步?
        假设处理一条消息要3秒（调LLM），如果不用异步，
        这3秒内任何新消息都收不到。
        用了异步，等待LLM回复时可以去收新消息，效率高很多。
    """
    addr = websocket.remote_address  # 连接者的IP和端口
    print(f"  [连接] NapCat 已接入 {addr}", flush=True)

    try:
        # async for: 异步迭代，每收到一条新消息就循环一次
        async for raw in websocket:
            try:
                # 收到的是一条JSON字符串，先解析
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue  # 不是JSON？跳过

            # OneBot v11 事件分为三种:
            #   post_type = "meta_event" → 心跳、生命周期
            #   post_type = "notice"     → 通知（戳一戳、入群等）
            #   post_type = "message"    → 消息（文字、图片等）
            post_type = data.get("post_type", "")

            # --- meta_event: 心跳包、NapCat启动/关闭 ---
            if post_type == "meta_event":
                meta_type = data.get("meta_event_type", "")
                if meta_type == "lifecycle":
                    print(f"  [生命周期] {data.get('sub_type', '')}", flush=True)
                continue  # 处理完就继续等下一帧

            # --- notice: 通知事件（戳一戳等）---
            if post_type == "notice":
                notice_type = data.get("notice_type", "")
                # 检查是不是"戳一戳"
                if notice_type == "notify" and data.get("sub_type") == "poke":
                    target_id = str(data.get("target_id", ""))
                    # 确认戳的是机器人自己
                    if BOT_QQ and target_id == BOT_QQ:
                        poker_uid = str(data.get("user_id", ""))
                        is_owner = (poker_uid == OWNER_QQ)
                        # 选一句话回复
                        if is_owner:
                            reply = random.choice(POKE_REPLIES_OWNER)
                        else:
                            reply = random.choice(POKE_REPLIES_OTHER)
                        # 发出去（群戳一起就发群里，私戳就发私聊）
                        gid = data.get("group_id")
                        if gid:
                            send_qq_message(str(gid), reply, "group")
                        else:
                            send_qq_message(poker_uid, reply, "private")
                        print(f"  [戳一戳] {'主人' if is_owner else '别人'}戳了{BOT_NAME} → {reply}", flush=True)
                continue

            # --- message: 收到消息 ---
            if post_type == "message":
                msg_type = data.get("message_type", "")          # "private" 或 "group"
                raw_msg = data.get("raw_message", "") or data.get("message", "")
                sender = data.get("sender", {})                  # 发送者信息
                nickname = sender.get("nickname", "?") or sender.get("card", "?")

                if msg_type == "private":
                    uid = str(data.get("user_id", ""))
                    try:
                        # asyncio.to_thread: 把同步函数放到线程池里跑
                        # 因为handle_message里有阻塞操作(调LLM、写文件)
                        # 放到线程里就不会阻塞事件循环
                        await asyncio.to_thread(handle_message, uid, nickname, raw_msg)
                    except Exception as e:
                        print(f"  [处理异常] 私聊消息处理失败: {e}", flush=True)

                elif msg_type == "group":
                    gid = str(data.get("group_id", ""))
                    uid = str(data.get("user_id", ""))
                    try:
                        await asyncio.to_thread(handle_message, uid, nickname, raw_msg, group_id=gid)
                    except Exception as e:
                        print(f"  [处理异常] 群聊消息处理失败: {e}", flush=True)

    except websockets.exceptions.ConnectionClosed:
        # 连接关闭是正常情况（NapCat关了、网络断了等），不用报错
        pass
    except Exception as e:
        # 其他异常打印出来方便排查
        import traceback
        print(f"  [WS异常] {e}", flush=True)
        traceback.print_exc()
    print(f"  [断开] {addr}", flush=True)


async def start_server(port: int):
    """
    启动WebSocket服务器，等待NapCat连接

    参数 port: 监听的端口号

    websockets.serve(处理函数, 地址, 端口):
      创建一个WebSocket服务器
      每当有新连接，就调用 handle_ws 函数

    asyncio.Event().wait():
      永久等待，不让程序退出
      Event像一个"永不亮起的绿灯"，wait()会一直等
    """
    print(f"  [服务器] 监听 ws://127.0.0.1:{port}")
    print(f"  [提示] 确保 NapCat WebUI 已添加反向 WS → ws://127.0.0.1:{port}")

    # async with: 异步上下文管理器，进入时启动服务器，退出时关闭
    async with websockets.serve(handle_ws, "127.0.0.1", port):
        await asyncio.Event().wait()  # 一直运行，直到Ctrl+C


# ==================== 第十一部分：启动辅助函数 ====================

def find_port() -> int:
    """
    端口自动探测：从起始端口开始试，找到第一个可用的

    原理: 尝试绑定(bind)一个端口
      - 绑定成功 → 端口空闲，返回这个端口号
      - 绑定失败(OSError) → 端口被占用，试下一个

    最多试5个端口 (8001~8005)
    """
    import socket
    for port in range(BOT_PORT_START, BOT_PORT_START + 5):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))  # 尝试占用
                return port                   # 成功！返回这个端口
            except OSError:
                print(f"  [跳过] 端口 {port} 被占用，尝试下一个...")
    print(f"  [错误] 端口 {BOT_PORT_START}-{BOT_PORT_START+4} 全被占用，请手动释放")
    return None


def wait_for_napcat() -> bool:
    """
    等待NapCat启动完成

    NapCat启动需要时间（加载协议、扫码登录等）
    这个函数每5秒检查一次NapCat的HTTP API是否可用
    最多等2分钟

    返回: True=NapCat就绪, False=超时
    """
    import time
    print("  [等待] 正在等待 NapCat 启动...", end="", flush=True)
    for i in range(24):  # 24次 × 5秒 = 2分钟
        try:
            r = requests.get(f"{NAPCAT_HTTP}/get_status", timeout=3)
            data = r.json()
            if data.get("data", {}).get("online"):
                print("\n  [OK] NapCat 在线，QQ 已登录")
                return True
            else:
                print(f"\n  [等待] QQ 未登录，请扫码... ({i+1}/24)")
        except:
            # 连不上，可能是NapCat还没启动
            if i % 4 == 0 and i > 0:
                print(f"\n  [等待] NapCat 未检测到，请确认已启动... ({i+1}/24)")
            else:
                print(".", end="", flush=True)  # 打印点表示在等待
        time.sleep(5)
    print(f"\n  [超时] 等待超时，请手动确认 NapCat 运行正常后重启{BOT_NAME}")
    return False


# ==================== 第十二部分：程序入口 ====================

def main():
    """
    主函数：程序的入口点

    启动顺序:
      1. 打印横幅
      2. 启动WebUI配置面板（端口8080）
      3. 检查API Key
      4. 等待NapCat上线
      5. 找可用端口
      6. 启动WebSocket服务器
      7. 等待Ctrl+C退出
    """
    # --- 打印启动横幅 ---
    print("=" * 44)
    print(f"  {BOT_NAME} · BaiYue  v2.0")
    print("  「我是 AI，但我懂你」")
    print(f"  NapCat API: {NAPCAT_HTTP}")
    print("=" * 44)

    # --- 启动WebUI ---
    start_webui(8080)  # 在后台线程启动网页配置面板

    # --- 检查配置 ---
    if not DEEPSEEK_KEY:
        print("  [警告] 未设置 DEEPSEEK_KEY，请在WebUI里配置: http://127.0.0.1:8080")

    # --- 等待NapCat ---
    if not wait_for_napcat():
        return  # 等不到NapCat就退出

    # --- 找端口 ---
    port = find_port()
    if port is None:
        return  # 没端口可用就退出

    # --- 启动服务器 ---
    try:
        # asyncio.run() 是Python异步编程的入口
        # 它创建一个事件循环，运行start_server，直到Ctrl+C
        asyncio.run(start_server(port))
    except KeyboardInterrupt:
        # Ctrl+C → 优雅退出
        print(f"\n  {BOT_NAME}：下次见，拍档。")


# Python的特殊变量 __name__
# 如果直接运行这个文件(python bot.py)，__name__ == "__main__" 为True
# 如果被其他文件import，__name__ 就是模块名，不会执行main()
# 这就是为什么 import 一个文件不会自动跑它的代码
if __name__ == "__main__":
    main()


"""
╔══════════════════════════════════════════════════════════════╗
║                     学完这个你应该懂了:                       ║
║                                                              ║
║  1. 怎么用Python接收WebSocket消息                            ║
║  2. 怎么调大语言模型API（DeepSeek/OpenAI都一样）              ║
║  3. 什么是系统提示词（System Prompt）                        ║
║  4. 怎么实现长期记忆 + 自动摘要                              ║
║  5. 怎么处理QQ的CQ码（表情、图片、@提及）                     ║
║  6. 怎么用正则表达式替换文本                                  ║
║  7. async/await异步编程基础                                   ║
║  8. 怎么调用命令行工具（edge-tts）                            ║
║  9. 怎么做异常处理和重试机制                                  ║
║  10. 怎么组织一个中等规模的Python项目                         ║
║                                                              ║
║  有不懂的随时问我！代码要多看多写才能记住 [酷]                 ║
╚══════════════════════════════════════════════════════════════╝
"""
