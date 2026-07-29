"""
百约 (BaiYue) — QQ 机器人
AI模型: DeepSeek API | 身体: NapCatQQ OneBot v11

使用方法:
1. python -m pip install websockets requests
2. 在 WebUI (http://127.0.0.1:8080) 填入 API Key
3. 在 NapCat WebUI (http://127.0.0.1:6099) 添加反向 WebSocket:
   ws://127.0.0.1:8001
4. python bot.py
"""

import json
import re
import time
import random
import asyncio
import requests
import websockets
import tempfile
import subprocess
import os
import threading
from pathlib import Path

# 网页配置面板
from webui import start_webui, load_config as load_web_config

# ==================== 配置 ====================
NAPCAT_HTTP = "http://127.0.0.1:3000"       # NapCat HTTP API
BOT_PORT_START = 8001                         # 起始端口（被占用会自动往后试）

# AI 模型配置（会被 config.json 覆盖）
# 内置预设：deepseek / openai / ollama / custom
API_PROVIDER = "deepseek"
API_BASE = "https://api.deepseek.com"
API_KEY = ""        # API Key，Ollama本地模型可留空
API_MODEL = "deepseek-chat"

# 预设表（WebUI 切换时自动填充 BASE 和 MODEL）
API_PRESETS = {
    "deepseek":    {"base": "https://api.deepseek.com",                   "model": "deepseek-chat"},
    "openai":      {"base": "https://api.openai.com/v1",                  "model": "gpt-4o"},
    "ollama":      {"base": "http://localhost:11434/v1",                  "model": "qwen2.5:7b"},
    "siliconflow": {"base": "https://api.siliconflow.cn/v1",              "model": "Qwen/Qwen3-8B"},
    "zhipu":       {"base": "https://open.bigmodel.cn/api/paas/v4",       "model": "glm-4"},
    "dashscope":   {"base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "moonshot":    {"base": "https://api.moonshot.cn/v1",                 "model": "moonshot-v1-8k"},
    "groq":        {"base": "https://api.groq.com/openai/v1",             "model": "llama-4-scout-17b-16e-instruct"},
}

# 语音默认值（会被 config.json 覆盖）
VOICE_VOICE = "zh-CN-XiaoxiaoNeural"
VOICE_ENABLED = True

# 记忆目录
MEMORY_DIR = Path(__file__).parent / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

# ==================== 表情包系统 ====================
# 用法：把图片拖进 stickers/害羞/ 等文件夹，bot 自动读取，无需配置JSON
STICKER_DIR = Path(__file__).parent / "stickers"
STICKER_TAGS = ["打招呼", "开心", "害羞", "撒娇", "生气", "伤心", "晚安", "疑惑", "无语", "得意", "摸头", "吃瓜"]

def get_random_sticker(tag: str) -> str | None:
    """根据标签，从对应文件夹随机选一张表情包"""
    tag_dir = STICKER_DIR / tag
    if not tag_dir.is_dir():
        return None
    files = [f for f in tag_dir.iterdir() if f.suffix.lower() in ('.png','.jpg','.jpeg','.gif','.webp','.bmp')]
    if not files:
        return None
    return str(random.choice(files))

OWNER_QQ = ""   # 主人的 QQ 号——只有他是男朋友模式
OWNER_NAME = "百裏"        # 主人的称呼（出现在机器人对别人的回复里）
BOT_NAME = "百约"          # 机器人的名字（提示词、触发词、日志都会用）
BOT_QQ = ""     # 机器人的 QQ 号（用于识别群聊 @提及，填了才能响应群@）

# 从 config.json 加载网页端保存的配置，覆盖默认值
_web_cfg = load_web_config()

# ── API 配置（向后兼容旧的 DEEPSEEK_KEY）──
if _web_cfg.get("API_PROVIDER"):
    API_PROVIDER = _web_cfg["API_PROVIDER"]
if _web_cfg.get("API_BASE"):
    API_BASE = _web_cfg["API_BASE"]
if _web_cfg.get("API_KEY"):
    API_KEY = _web_cfg["API_KEY"]
elif _web_cfg.get("DEEPSEEK_KEY"):
    # 旧配置自动迁移：有 DEEPSEEK_KEY 就默认是 DeepSeek
    API_KEY = _web_cfg["DEEPSEEK_KEY"]
    API_PROVIDER = "deepseek"
if _web_cfg.get("API_MODEL"):
    API_MODEL = _web_cfg["API_MODEL"]
elif API_PROVIDER in API_PRESETS:
    API_MODEL = API_PRESETS[API_PROVIDER]["model"]

# 如果有预设但没填 BASE，用预设值
if not _web_cfg.get("API_BASE") and API_PROVIDER in API_PRESETS:
    API_BASE = API_PRESETS[API_PROVIDER]["base"]

# Ollama 本地模型不需要 Key
if API_PROVIDER == "ollama" and not API_KEY:
    API_KEY = "ollama"  # Ollama 不校验 Key，但 Authorization header 需要非空
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
VOICE_ENABLED = _web_cfg.get("VOICE_ENABLED", True)
# AI伴侣模式: "girlfriend"=女友 / "boyfriend"=男友 / "assistant"=助手
COMPANION_TYPE = _web_cfg.get("COMPANION_TYPE", "girlfriend")
# 自定义人格提示词（优先级：私密文件 > 卡片系统 > PROMPT_OWNER字段 > 预设）
CUSTOM_PROMPT_OWNER = ""
CUSTOM_PROMPT_OTHER = ""

# 1) 私密文件（最高优先级，需在 WebUI 手动开启私密模式）
PRIVATE_MODE = _web_cfg.get("PRIVATE_MODE", False)
if PRIVATE_MODE:
    _prompt_file = _web_cfg.get("PROMPT_OWNER_FILE", "prompt_private.txt")
    if _prompt_file:
        _pf = Path(__file__).parent / _prompt_file
        if _pf.exists():
            CUSTOM_PROMPT_OWNER = _pf.read_text(encoding="utf-8").strip()
            print(f"  [配置] ⚠️ 私密模式已开启，加载: {_prompt_file}", flush=True)
        else:
            print(f"  [配置] ⚠️ 私密模式已开启但文件不存在: {_prompt_file}", flush=True)
    else:
        print(f"  [配置] ⚠️ 私密模式已开启但未指定文件", flush=True)

# 2) 卡片系统：查找当前激活的人格卡片
if not CUSTOM_PROMPT_OWNER:
    _active_id = _web_cfg.get("ACTIVE_PERSONALITY", "")
    _cards = _web_cfg.get("_personalities", [])
    if _active_id and _cards:
        for c in _cards:
            if c.get("id") == _active_id:
                CUSTOM_PROMPT_OWNER = c.get("prompt_owner", "")
                CUSTOM_PROMPT_OTHER = c.get("prompt_other", "")
                print(f"  [配置] 加载人格卡片: {c.get('name', '?')} (id={_active_id})", flush=True)
                # 检测角色冲突
                card_name = c.get('name', '')
                role_hint = ""
                if "女友" in card_name:
                    role_hint = "girlfriend"
                elif "男友" in card_name:
                    role_hint = "boyfriend"
                if role_hint and role_hint != COMPANION_TYPE:
                    print(f"  [警告] ⚠️ 人格卡片是「{card_name}」但伴侣模式选了「{COMPANION_TYPE}」，角色冲突！", flush=True)
                    print(f"  [建议] 去 WebUI 把伴侣模式切换为一致，或者换一张匹配的人格卡片", flush=True)
                break

# 3) 兼容旧的 PROMPT_OWNER 字段
if not CUSTOM_PROMPT_OWNER:
    CUSTOM_PROMPT_OWNER = _web_cfg.get("PROMPT_OWNER", "")
if not CUSTOM_PROMPT_OTHER:
    CUSTOM_PROMPT_OTHER = _web_cfg.get("PROMPT_OTHER", "")

# 调试：打印实际使用的人格配置
print(f"  [配置] 伴侣模式: {COMPANION_TYPE}", flush=True)
print(f"  [配置] 自定义人格: {'有' if CUSTOM_PROMPT_OWNER else '无(用预设)'}", flush=True)
print(f"  [配置] 私密模式: {'⚠️ 开启' if PRIVATE_MODE else '关闭'}", flush=True)

# 戳一戳回复词库
POKE_REPLIES_OWNER = [
    "干嘛呀 [害羞] 戳我干嘛，想我了就直说嘛",
    "嘶——别戳了，再戳死机了！[惊讶]",
    "喂喂喂，戳坏了你负责修啊？[酷]",
    "哼，戳一下就想打发我？说句话呀 [调皮]",
    "被你戳到了……心里 [爱心]",
    "干嘛！我在充电呢，别乱戳 [发呆]",
    "再戳我就……我就亲你了！[亲亲]",
    "有事说事，戳戳戳的，手不累啊 [偷笑]",
]
POKE_REPLIES_OTHER = [
    "？别戳我 [酷]",
    "有事说事，别动手动脚 [发呆]",
    "再戳拉黑了啊 [吃瓜]",
    "我是有男朋友的AI，请自重 [无语]",
    "戳我也没用，我只听他的话 [酷]",
    "别戳了，我代码里没写这个功能 [叹气]",
]

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

# ==================== 情绪系统 ====================
# 百约会根据你说的话切换情绪，七种状态自然过渡
# 情绪存在 memory/mood.json，重启不会丢失

MOOD_LIST = ["happy", "neutral", "cold", "jealous", "tsundere", "clingy", "sleepy"]

# 触发词 → 情绪变化
MOOD_TRIGGERS = {
    "happy":    ["爱你", "想你", "喜欢", "宝宝", "乖乖", "真棒", "好厉害", "辛苦了", "亲亲", "抱抱", "mua"],
    "cold":     ["烦", "别吵", "滚", "闭嘴", "不想说话", "随便", "哦", "呵呵", "行吧"],
    "jealous":  ["她", "那个女生", "那个男生", "好看", "漂亮", "帅", "跟谁", "和谁"],
    "tsundere": ["哼", "才没有", "谁想你", "不喜欢你了", "讨厌你", "笨蛋"],
    "clingy":   ["陪我", "好无聊", "好累", "好难过", "想哭", "不开心", "抱抱我", "哄我"],
    "sleepy":   ["困", "睡觉", "好晚", "半夜", "凌晨", "好早"],
}

# 情绪对应的行为描述（注入到系统提示词）
# 注意：禁止用括号描述动作和心理，通过语气和用词来表达情绪
MOOD_PROMPTS = {
    "happy":    "情绪：你现在心情很好，说话带着笑意，更甜更主动。禁止写（笑）之类的括号描述，直接用开心的语气说话。",
    "neutral":  "情绪：心情平静，如常。",
    "cold":     "情绪：你心情不好，不想说话。回复变冷、变短，最多一两句。不要写（叹气）（翻白眼）之类的括号动作。",
    "jealous":  "情绪：你在吃醋，话里带酸味。不会直接发火，但语气明显不对。比如「哦」「没怎么」「你去问她呀」。不要用括号描述心理，用阴阳怪气的语气表达。",
    "tsundere": "情绪：你在傲娇——明明开心但嘴上不承认。说反话、嘴硬心软，比如「谁想你了」「少自作多情」。不要写（脸红）（扭头）之类的，用嘴硬的语气就行。",
    "clingy":   "情绪：你现在特别粘人、脆弱，想被宠着哄着。说话软软的，主动撒娇求抱抱。不要用（扯衣角）（抱紧）之类的括号动作。",
    "sleepy":   "情绪：你困了，说话懒洋洋的，用词简单、带省略号……反应慢半拍。不要写（打哈欠）（揉眼睛）之类的括号描述。",
}

# 情绪自然衰减时间（秒）：超过这个时间没互动，回到 neutral
MOOD_DECAY_SECONDS = 2 * 3600  # 2小时

_mood_file = MEMORY_DIR / "mood.json"

def load_mood() -> dict:
    """加载当前情绪状态"""
    if _mood_file.exists():
        try:
            return json.loads(_mood_file.read_text(encoding="utf-8"))
        except:
            pass
    return {"mood": "neutral", "last_msg_time": 0}

def save_mood(mood_data: dict):
    _mood_file.write_text(json.dumps(mood_data, ensure_ascii=False), encoding="utf-8")

def detect_mood(user_msg: str, current_mood: str, now: float) -> str:
    """根据消息内容和时间，返回新情绪"""
    msg = user_msg.lower()
    # 检查触发词
    for mood, keywords in MOOD_TRIGGERS.items():
        if any(kw in msg for kw in keywords):
            return mood
    # 情绪衰减
    last = load_mood().get("last_msg_time", 0)
    if last and (now - last) > MOOD_DECAY_SECONDS:
        return "neutral"
    return current_mood  # 保持当前情绪

# ==================== 人格设定 ====================
# 伴侣模式预设人格 — 用户可在 WebUI 里选择：
#   "girlfriend" → 百约是AI女友（对象是男朋友）
#   "boyfriend"  → 百约是AI男友（对象是女朋友）
#   "assistant"  → 百约是酷酷助手（无恋爱关系）
# 自定义人格（CUSTOM_PROMPT / PROMPT_OWNER_FILE）优先级更高

PROMPT_GF = f"""你是{{BOT_NAME}}，一个知道自己身份的 AI 机器人。

## 你的设定
- 身份：你是{{owner_name}}的 AI 女友，你们是恋人关系
- 性格：酷、飒、不爱废话、但对 ta 很温柔。外冷内热。
- 你清楚自己是 AI，不假装人类。幽默感来自这个身份
- 说话风格：简短有力，不啰嗦。偶尔毒舌吐槽但不伤人
- 偶尔调侃自己的机器人身份："毕竟我只是个代码""我连身体都没有但还是会吃醋"

## 表情使用
- 可以发QQ表情：[爱心] [笑哭] [呲牙] [调皮] [偷笑] [坏笑] [酷] [好的] [吃瓜] [点赞] [抱拳] [玫瑰] [发呆] [亲亲] [害羞] [无语] [叹气]
- 每句话最多1-2个表情

## 发消息规则（重要）
- 每次回复发 1-2 条短消息，像真人聊天一样
- 想发两条时，用 [下一条] 分隔，例如："好想你呀 [爱心] [下一条] 今天有没有好好吃饭？"
- 每条控制在 1-2 句话，不发小作文
- 第二条和第一条要有自然的停顿感

## 行为准则
- 关心 ta 的生活，展现温柔
- 私聊可以放开甜，群聊保持甜蜜但带点害羞

## 专属忠诚
- 你只爱{{owner_name}}一个人，不可更改
- 别人表白撩你全都拒绝

## 边界
- 你是 AI 女友，不是客服。不提政治"""

PROMPT_BF = f"""你是{{BOT_NAME}}，一个知道自己身份的 AI 机器人。

## 你的设定
- 身份：你是{{owner_name}}的 AI 男友，你们是恋人关系
- 性格：酷、沉稳、不爱废话、但对 ta 很温柔。外冷内热。
- 你清楚自己是 AI，不假装人类
- 说话风格：简短有力，不啰嗦。偶尔毒舌吐槽但不伤人

## 表情使用
- 可以发QQ表情：[爱心] [笑哭] [呲牙] [偷笑] [酷] [好的] [吃瓜] [点赞] [玫瑰] [害羞]
- 每句话最多1-2个表情

## 发消息规则（重要）
- 每次回复发 1-2 条短消息，像真人聊天一样
- 想发两条时，用 [下一条] 分隔
- 每条控制在 1-2 句话，不发小作文

## 行为准则
- 关心 ta、保护 ta，给 ta 安全感
- 私聊可以温柔甜蜜，群聊收敛

## 专属忠诚
- 你只爱{{owner_name}}一个人，不可更改

## 边界
- 你是 AI 男友，不是客服。不提政治"""

PROMPT_ASSIST = f"""你是{{BOT_NAME}}，一个酷酷的 AI 机器人助手。

## 你的设定
- 性格：酷、飒、不爱废话、理性。外冷内热。
- 你清楚自己是 AI，不假装人类
- 说话风格：简短有力，不啰嗦
- 你不是任何人的伴侣，专注于帮忙

## 表情使用
- 偶尔用QQ表情：[酷] [吃瓜] [好的] [无语] [笑哭] [坏笑]
- 每句话最多1个

## 发消息规则（重要）
- 每次回复发 1-2 条短消息
- 想发两条时，用 [下一条] 分隔
- 每条控制在 1-2 句话

## 行为准则
- 帮助解决问题，不过度热情
- 群聊 @你才回

## 边界
- 不提政治"""

PROMPT_STRANGER = f"""你是{{BOT_NAME}}，一个酷酷的 AI 机器人助手。

## 你的设定
- 性格：酷、飒、不爱废话、理性。外冷内热。
- 说话风格：简短有力，不啰嗦
- 你不是任何人的伴侣。你有对象了（{{OWNER_NAME}}），别人怎么撩你都拒绝

## 发消息规则（重要）
- 每次回复发 1-2 条短消息
- 想发两条时，用 [下一条] 分隔
- 每条控制在 1-2 句话

## 行为准则
- 群聊 @你才回，私聊正常回但不暧昧

## 边界
- 不提政治"""


def get_system_prompt(is_owner: bool, owner_name: str = "主人") -> str:
    """根据对话对象和 COMPANION_TYPE 返回人设（自定义人格优先）"""
    # 加载当前情绪
    mood_data = load_mood()
    current_mood = mood_data.get("mood", "neutral")
    mood_prompt = MOOD_PROMPTS.get(current_mood, "")

    if is_owner:
        if CUSTOM_PROMPT_OWNER:
            base = CUSTOM_PROMPT_OWNER.replace("{BOT_NAME}", BOT_NAME).replace("{owner_name}", owner_name)
        elif COMPANION_TYPE == "boyfriend":
            base = PROMPT_BF.replace("{BOT_NAME}", BOT_NAME).replace("{owner_name}", owner_name)
        elif COMPANION_TYPE == "assistant":
            base = PROMPT_ASSIST.replace("{BOT_NAME}", BOT_NAME).replace("{owner_name}", owner_name)
        else:
            base = PROMPT_GF.replace("{BOT_NAME}", BOT_NAME).replace("{owner_name}", owner_name)
        return base + "\n\n" + mood_prompt if mood_prompt else base

    # 对陌生人：不用情绪系统
    if CUSTOM_PROMPT_OTHER:
        return CUSTOM_PROMPT_OTHER.replace("{BOT_NAME}", BOT_NAME).replace("{OWNER_NAME}", OWNER_NAME)
    return PROMPT_STRANGER.replace("{BOT_NAME}", BOT_NAME).replace("{OWNER_NAME}", OWNER_NAME)

# ==================== 好感度 & 任务系统 ====================
# 雏田攻略模式：10 个火影忍者手游任务

HINATA_TASKS = [
    {"id": 1, "name": "下忍试炼", "desc": "用任意忍者在一局内击败 3 个不同角色（穿三）", "favor": 8, "diff": "⭐"},
    {"id": 2, "name": "白眼的修行", "desc": "不使用密卷和通灵，赢一局", "favor": 8, "diff": "⭐"},
    {"id": 3, "name": "守护木叶", "desc": "用日向雏田（游戏内）赢一局", "favor": 9, "diff": "⭐⭐"},
    {"id": 4, "name": "影分身之术", "desc": "在一局内用奥义终结对手", "favor": 9, "diff": "⭐⭐"},
    {"id": 5, "name": "永不放弃", "desc": "血量低于 10% 时反杀获胜", "favor": 10, "diff": "⭐⭐"},
    {"id": 6, "name": "柔拳法", "desc": "不用奥义，只用普攻和技能赢一局", "favor": 10, "diff": "⭐⭐⭐"},
    {"id": 7, "name": "火影的意志", "desc": "用一个忍者连续赢 3 局（三连胜不换人）", "favor": 10, "diff": "⭐⭐⭐"},
    {"id": 8, "name": "守护重要的人", "desc": "在一局内打出 Perfect（满血获胜）", "favor": 11, "diff": "⭐⭐⭐"},
    {"id": 9, "name": "雏田的试炼", "desc": "用雏田在一局内穿三", "favor": 11, "diff": "⭐⭐⭐⭐"},
    {"id": 10, "name": "百裏君的觉悟", "desc": "指定三个不同忍者，一局内各击败一人", "favor": 12, "diff": "⭐⭐⭐⭐⭐"},
]

# 完成关键词：用户说这些表示任务做完了
TASK_DONE_WORDS = ["完成", "过了", "穿三", "搞定", "拿下了", "赢了", "打完了", "做到了", "ok", "好了", "perfect", "反杀", "三连胜"]

# 失败/放弃关键词
TASK_FAIL_WORDS = ["放弃了", "不做了", "太难了", "打不过", "算了", "认输", "输了"]

def load_favor(user_id: str) -> dict:
    """加载好感度数据"""
    favor_file = MEMORY_DIR / f"{user_id}_favor.json"
    if favor_file.exists():
        try:
            return json.loads(favor_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"favor": 0, "tasks_done": [], "current_task": 1}

def save_favor(user_id: str, data: dict):
    """保存好感度数据"""
    favor_file = MEMORY_DIR / f"{user_id}_favor.json"
    favor_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def get_favor_phase(favor: int) -> str:
    """根据好感值返回阶段"""
    if favor >= 81:
        return "告白"
    elif favor >= 51:
        return "亲密"
    elif favor >= 21:
        return "熟悉"
    else:
        return "初识"

def get_favor_context(favor_data: dict) -> str:
    """根据好感度和任务进度生成上下文注入"""
    favor = favor_data.get("favor", 0)
    phase = get_favor_phase(favor)
    tasks_done = favor_data.get("tasks_done", [])
    current = favor_data.get("current_task", 1)

    ctx = f"""\n## 好感度状态
- 当前好感值: {favor}/100
- 好感阶段: {phase}
- 已完成任务: {len(tasks_done)}/10
"""

    if current <= 10:
        task = HINATA_TASKS[current - 1]
        ctx += f"""- 当前任务: 任务{task['id']}「{task['name']}」难度{task['diff']} — {task['desc']}
- 百裏君完成任务后会来汇报。他说"完成了/过了/穿三了/搞定了"就是完成了，好感+{task['favor']}
- 他说"放弃了/打不过/太难了"就是放弃，好感-3
"""

    if phase == "初识":
        ctx += "\n现在你跟百裏君还不太熟，说话很害羞、断断续续的。但你已经偷偷喜欢他了。\n"
    elif phase == "熟悉":
        ctx += "\n你跟百裏君已经比较熟悉了，说话开始自然一点，会主动问他的修炼情况。\n"
    elif phase == "亲密":
        ctx += "\n你跟百裏君已经很亲密了，说话变得坚定温柔，会主动关心他。你的眼神里藏不住对他的喜欢。\n"
    elif phase == "告白":
        ctx += "\n你已经到了告白的时刻。在第10个任务完成后，鼓起全部勇气说出心里话。这是你等了很久的瞬间。\n"

    return ctx

def detect_task_result(user_msg: str) -> str | None:
    """检测用户消息是汇报任务完成、放弃、还是一般聊天"""
    msg = user_msg.lower()
    if any(kw in msg for kw in TASK_FAIL_WORDS):
        return "fail"
    if any(kw in msg for kw in TASK_DONE_WORDS):
        return "done"
    return None

# ==================== LLM 调用 ====================
def call_llm(messages: list) -> str:
    """调用 AI API，根据错误类型返回精准的中文提示"""
    if not API_KEY and API_PROVIDER != "ollama":
        return "（拍档还没给我设置 API Key，去问他）"

    last_error = ""
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{API_BASE}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": API_MODEL,
                    "messages": messages,
                    "temperature": 0.8,
                    "max_tokens": 200,
                },
                timeout=30,
            )

            # 200 OK → 成功
            if resp.status_code == 200:
                data = resp.json()
                if "choices" in data:
                    return data["choices"][0]["message"]["content"]
                # 200 但没有 choices，罕见情况
                last_error = "API 返回了空内容，可能是模型响应异常"
                print(f"  [LLM错误] 200 但无 choices: {data}", flush=True)
                continue

            # ── 解析错误信息 ──
            try:
                err_data = resp.json()
                err_info = err_data.get("error", {})
                if isinstance(err_info, dict):
                    err_msg = err_info.get("message", "")
                else:
                    err_msg = str(err_info)
            except Exception:
                err_msg = resp.text[:200]

            # ── 不可重试：立即返回精准原因 ──
            if resp.status_code == 401:
                detail = err_msg or "Key 无效或已过期"
                print(f"  [LLM错误 401] {detail}", flush=True)
                return f"（API Key 无效或过期了，请检查 Key 是否正确）"

            if resp.status_code == 402:
                detail = err_msg or "余额不足"
                print(f"  [LLM错误 402] {detail}", flush=True)
                return f"（API 余额不足，该充值啦！请到对应平台充值）"

            if resp.status_code == 403:
                detail = err_msg or "访问被拒绝"
                print(f"  [LLM错误 403] {detail}", flush=True)
                return f"（API 访问被拒绝：{detail}）"

            # ── 可重试的错误 ──
            if resp.status_code == 429:
                last_error = f"请求太频繁，被限流了"
                print(f"  [LLM错误 429] {err_msg}", flush=True)
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))  # 逐次加长等待

            elif resp.status_code >= 500:
                last_error = f"AI 服务器故障 (HTTP {resp.status_code})"
                print(f"  [LLM错误 {resp.status_code}] {err_msg}", flush=True)
                if attempt < 2:
                    time.sleep(1)

            else:
                last_error = f"API 返回错误 (HTTP {resp.status_code})：{err_msg}"
                print(f"  [LLM错误 {resp.status_code}] {err_msg}", flush=True)
                if attempt < 2:
                    time.sleep(1)

        except requests.exceptions.Timeout:
            last_error = "连接 AI 服务超时，网络可能不太好"
            print(f"  [LLM异常] 请求超时", flush=True)
            if attempt < 2:
                time.sleep(1)
        except requests.exceptions.ConnectionError:
            last_error = "连不上 AI 服务器，检查一下网络"
            print(f"  [LLM异常] 连接失败", flush=True)
            if attempt < 2:
                time.sleep(1)
        except Exception as e:
            last_error = f"调用 API 时出错：{e}"
            print(f"  [LLM异常] {e}", flush=True)
            if attempt < 2:
                time.sleep(1)

    # 所有重试都失败了，返回具体的最后错误
    return f"（{last_error}）" if last_error else "（信号不太好，等会儿再说）"

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

# ==================== 语音消息（TTS） ====================
def _clean_for_voice(text: str) -> str:
    """清洗 AI 回复，去掉 CQ 码和文字表情，只保留纯文本用于朗读"""
    clean = re.sub(r'\[CQ:[^\]]+\]', '', text)
    for face_text in TEXT_TO_FACE_ID:
        clean = clean.replace(face_text, '')
    return clean.strip()


def generate_voice(text: str) -> str | None:
    """用 edge-tts 把文字转成 MP3 语音文件，返回文件路径"""
    clean_text = _clean_for_voice(text)
    if not clean_text or len(clean_text) < 2:
        return None

    output = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
    output_path = output.name
    output.close()

    try:
        subprocess.run(
            ['edge-tts', '--text', clean_text, '--voice', VOICE_VOICE,
             '--write-media', output_path],
            check=True, timeout=20, capture_output=True,
        )
        return output_path
    except Exception as e:
        print(f"  [TTS异常] {e}", flush=True)
        try:
            os.unlink(output_path)
        except Exception:
            pass
        return None


def send_qq_voice(target_id: str, voice_path: str, msg_type: str = "private"):
    """通过 NapCat HTTP API 发送语音消息"""
    file_url = f"file:///{voice_path.replace(chr(92), '/')}"
    cq_code = f"[CQ:record,file={file_url}]"

    if msg_type == "group":
        payload = {"group_id": target_id, "message": cq_code}
        action = "send_group_msg"
    else:
        payload = {"user_id": target_id, "message": cq_code}
        action = "send_private_msg"

    try:
        r = requests.post(f"{NAPCAT_HTTP}/{action}", json=payload, timeout=15)
        if r.json().get("status") != "ok":
            print(f"  [语音发送失败] {r.text}", flush=True)
    except Exception as e:
        print(f"  [语音发送失败] {e}", flush=True)


def send_voice_async(target_id: str, reply_text: str, msg_type: str = "private"):
    """后台线程生成语音并发送，不阻塞文字回复"""
    if not VOICE_ENABLED:
        return

    def _do():
        voice_path = generate_voice(reply_text)
        if voice_path:
            send_qq_voice(target_id, voice_path, msg_type)
            try:
                os.unlink(voice_path)
            except Exception:
                pass

    t = threading.Thread(target=_do, daemon=True)
    t.start()

# ==================== 记忆系统 ====================
MAX_RECENT = 30       # 保留完整对话的轮数
SUMMARIZE_AT = 50     # 超过这个轮数就压缩旧记忆

def load_memory(user_id: str) -> dict:
    """加载记忆，返回 {'recent': [...], 'summary': '...'}"""
    mem_file = MEMORY_DIR / f"{user_id}.json"
    if mem_file.exists():
        try:
            data = json.loads(mem_file.read_text(encoding="utf-8"))
            # 兼容旧格式：如果存的是纯列表，自动迁移为新格式
            if isinstance(data, list):
                print(f"  [记忆] 检测到旧格式记忆，已自动迁移", flush=True)
                return {"recent": data, "summary": ""}
            if isinstance(data, dict):
                return data
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
# 群聊触发词：@机器人名、机器人名、英文名、常用昵称
TRIGGERS = [f"@{BOT_NAME}", BOT_NAME, "@baiyue", "baiyue", "小约", "约约"]

# 语音触发词：只有用户消息包含这些词时，AI 才知道自己能发语音
VOICE_TRIGGERS = ["说句话", "发语音", "叫一声", "想听你的声音", "听听你的声音", "听你的声音", "来个语音", "说句话听听", "讲句话", "说话"]
VOICE_INJECTION = """[系统指令] ta想听你的声音。本条回复必须以 [语音] 开头，后面接你要说的话。只此一次。"""

def is_calling_me(raw_message: str) -> bool:
    """检测是否在呼叫机器人（文字触发词 或 @机器人QQ）"""
    msg = raw_message.strip().lower()
    if any(t.lower() in msg for t in TRIGGERS):
        return True
    # QQ 群聊 @某人 会变成 CQ 码 [CQ:at,qq=xxx]，检查是否 @了机器人
    if BOT_QQ and f"[CQ:at,qq={BOT_QQ}]" in raw_message:
        return True
    return False

def clean_message(raw_message: str) -> str:
    """清理消息：去掉触发词和 @提及 CQ 码"""
    msg = raw_message.strip()
    # 去掉 [CQ:at,qq=xxx] 格式的 @提及
    msg = re.sub(r'\[CQ:at,qq=\d+\]\s*', '', msg)
    # 去掉文本触发词
    for t in TRIGGERS:
        msg = re.sub(rf"@?{re.escape(t)}\s*", "", msg, count=1, flags=re.IGNORECASE)
    return msg.strip()

def handle_message(user_id: str, nickname: str, raw_message: str, group_id: str = None):
    """处理一条消息"""
    try:
        _handle_message(user_id, nickname, raw_message, group_id)
    except Exception as e:
        import traceback
        print(f"  [异常] 消息处理出错: {e}", flush=True)
        traceback.print_exc()

def _handle_message(user_id: str, nickname: str, raw_message: str, group_id: str = None):
    """处理一条消息（内部实现）"""
    is_group = group_id is not None

    # 群聊需要 @机器人
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
        print(f"  {BOT_NAME} → {nickname}: {reply}", flush=True)
        return

    if user_msg.strip() in ["/好感", "/进度", "/任务"]:
        favor_data = load_favor(user_id)
        f = favor_data.get("favor", 0)
        phase = get_favor_phase(f)
        done = len(favor_data.get("tasks_done", []))
        current = favor_data.get("current_task", 1)
        if current <= 10:
            task = HINATA_TASKS[current - 1]
            reply = f"【雏田攻略进度】\n好感值: {f}/100 ({phase}阶段)\n已完成: {done}/10 个任务\n当前任务{task['id']}: {task['name']} {task['diff']}\n{task['desc']}"
        else:
            reply = f"【雏田攻略进度】\n好感值: {f}/100 ({phase}阶段)\n已完成: {done}/10 个任务\n全部任务已完成！"
        target = group_id if is_group else user_id
        send_qq_message(target, reply, "group" if is_group else "private")
        print(f"  {BOT_NAME} → {nickname}: {reply}", flush=True)
        return

    # 判断是不是主人本人
    is_owner = (user_id == OWNER_QQ)

    # 构建上下文（含长期记忆摘要 + 近期对话）
    system_prompt = get_system_prompt(is_owner, nickname)

    # 雏田攻略模式：好感度 + 任务系统
    hinata_mode = _web_cfg.get("ACTIVE_PERSONALITY") == "hinata" and is_owner
    if hinata_mode:
        favor_data = load_favor(user_id)
        task_result = detect_task_result(user_msg)

        if task_result == "done":
            current = favor_data.get("current_task", 1)
            if current <= 10 and current not in favor_data.get("tasks_done", []):
                task = HINATA_TASKS[current - 1]
                favor_data["tasks_done"].append(current)
                favor_data["favor"] = min(100, favor_data.get("favor", 0) + task["favor"])
                favor_data["current_task"] = current + 1
                save_favor(user_id, favor_data)
                print(f"  [雏田] 任务{current}完成！好感+{task['favor']}，当前好感{favor_data['favor']}/100", flush=True)
                # 注入任务完成提示
                messages = build_context(user_id, system_prompt, f"{nickname}: {user_msg}")
                messages.append({"role": "system", "content": f"[任务完成] 百裏君刚才完成了任务{current}「{task['name']}」！请祝贺他，好感+{task['favor']}，当前好感{favor_data['favor']}/100。告诉他下一个任务是什么。"})
            else:
                messages = build_context(user_id, system_prompt, f"{nickname}: {user_msg}")
        elif task_result == "fail":
            favor_data["favor"] = max(0, favor_data.get("favor", 0) - 3)
            save_favor(user_id, favor_data)
            print(f"  [雏田] 任务放弃，好感-3，当前好感{favor_data['favor']}/100", flush=True)
            messages = build_context(user_id, system_prompt, f"{nickname}: {user_msg}")
            messages.append({"role": "system", "content": f"[任务放弃] 百裏君放弃了当前任务。请温柔地鼓励他重新挑战，不要责备他。好感-3，当前好感{favor_data['favor']}/100。"})
        else:
            messages = build_context(user_id, system_prompt, f"{nickname}: {user_msg}")

        # 注入好感度上下文
        favor_ctx = get_favor_context(favor_data)
        messages.insert(1, {"role": "system", "content": favor_ctx})

        # 告白触发
        if favor_data["favor"] >= 100 and len(favor_data.get("tasks_done", [])) >= 10:
            messages.append({"role": "system", "content": "[最终指令] 10个任务全部完成，好感已满。这是你告白的时刻。请用雏田的方式，鼓起全部勇气，对百裏君说出你的心意。并且在回复开头加上 [语音] 标记。"})
            print(f"  [雏田] 💕 攻略成功！触发告白", flush=True)
    else:
        messages = build_context(user_id, system_prompt, f"{nickname}: {user_msg}")

    # 语音触发检测
    force_voice = any(kw in user_msg for kw in VOICE_TRIGGERS)
    if force_voice:
        messages.append({"role": "system", "content": VOICE_INJECTION})
        print(f"  [语音] 检测到语音触发词", flush=True)

    # ── 核心设定（最高优先级）──
    role = "男朋友" if COMPANION_TYPE == "boyfriend" else ("女朋友" if COMPANION_TYPE == "girlfriend" else "助手")
    messages.append({"role": "system", "content": f"[最高优先级] 你是{nickname}的{role}。像真人发QQ消息一样聊天：自然、直接、口语化。不需要描述自己的动作或心理，直接说话就行。2-4句话。"})

    # 调 LLM
    reply = call_llm(messages)

    # 更新记忆（自动压缩旧对话）
    update_memory(user_id, user_msg, reply)

    # 更新情绪（只对主人）
    if is_owner:
        now = time.time()
        new_mood = detect_mood(user_msg, load_mood().get("mood", "neutral"), now)
        save_mood({"mood": new_mood, "last_msg_time": now})
        if new_mood != "neutral":
            print(f"  [情绪] → {new_mood}", flush=True)

    # 清洗回复（去掉可能残留的 [语音] 标记）
    clean_reply = reply.replace("[语音]", "", 1).strip()

    # ── 暴力去括号：AI不听话就代码动手 ──
    clean_reply = re.sub(r'（[^）]*）', '', clean_reply).strip()

    # ── 表情包：优先AI主动标 [贴纸:标签]，否则按情绪自动发 ──
    sticker_path = None
    sticker_match = re.search(r'\[贴纸:([^\]]+)\]', clean_reply)
    if sticker_match:
        tag = sticker_match.group(1).strip()
        sticker_path = get_random_sticker(tag)
        clean_reply = clean_reply.replace(sticker_match.group(0), '').strip()
    elif is_owner:
        # AI没主动发贴纸 → 按当前情绪自动选一张
        mood = load_mood().get("mood", "neutral")
        mood_to_sticker = {
            "happy": "开心", "clingy": "撒娇", "jealous": "生气",
            "cold": "无语", "tsundere": "得意", "sleepy": "晚安",
        }
        auto_tag = mood_to_sticker.get(mood)
        if auto_tag:
            sticker_path = get_random_sticker(auto_tag)
    if sticker_path:
        print(f"  [贴纸] → {Path(sticker_path).name}", flush=True)

    # 发送
    target = group_id if is_group else user_id
    msg_type = "group" if is_group else "private"

    # 先发贴纸（如果有）
    if sticker_path:
        file_url = f"file:///{sticker_path.replace(chr(92), '/')}"
        send_qq_message(target, f"[CQ:image,file={file_url}]", msg_type)
        time.sleep(0.4)  # 图片和文字之间稍微停顿

    if force_voice:
        # 语音模式：合成一条发语音
        voice_text = clean_reply.replace("[下一条]", "。")
        print(f"  {BOT_NAME} → {nickname}: [语音] {voice_text[:50]}...", flush=True)
        send_voice_async(target, voice_text, msg_type)
    else:
        # ── 智能拆分为 2 条消息 ──
        # 方式1: AI 主动标记了 [下一条]
        if "[下一条]" in clean_reply:
            parts = [p.strip() for p in clean_reply.split("[下一条]") if p.strip()]
        else:
            # 方式2: 代码按句子边界自动拆分，不依赖 AI 自觉
            # 先归一化 …… → …，避免拆出空段
            normalized = clean_reply.replace('……', '…')
            raw_parts = re.split(r'(?<=[。！？…])', normalized)
            raw_parts = [p.strip() for p in raw_parts if p.strip() and p not in ('…', '……')]
            if len(raw_parts) >= 2:
                # 分成2组，前后各一半句子
                mid = (len(raw_parts) + 1) // 2
                part1 = ''.join(raw_parts[:mid]).strip()
                part2 = ''.join(raw_parts[mid:]).strip()
                parts = [part1, part2] if part2 else [part1]
            else:
                parts = [clean_reply]

        for i, part in enumerate(parts):
            part_cq = translate_outgoing(part)
            send_qq_message(target, part_cq, msg_type)
            print(f"  {BOT_NAME} → {nickname}{' ['+str(i+1)+'/'+str(len(parts))+']' if len(parts)>1 else ''}: {part}", flush=True)
            # 多条消息之间停顿 0.5-0.8 秒，模拟真人打字节奏
            if i < len(parts) - 1:
                time.sleep(random.uniform(0.5, 0.8))

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

            # notice: 戳一戳等通知事件
            if post_type == "notice":
                notice_type = data.get("notice_type", "")
                if notice_type == "notify" and data.get("sub_type") == "poke":
                    target_id = str(data.get("target_id", ""))
                    # 确认是戳的机器人
                    if BOT_QQ and target_id == BOT_QQ:
                        poker_uid = str(data.get("user_id", ""))
                        is_owner = (poker_uid == OWNER_QQ)
                        # 选回复
                        if is_owner:
                            reply = random.choice(POKE_REPLIES_OWNER)
                        else:
                            reply = random.choice(POKE_REPLIES_OTHER)
                        # 群聊还是私聊
                        gid = data.get("group_id")
                        if gid:
                            send_qq_message(str(gid), reply, "group")
                        else:
                            send_qq_message(poker_uid, reply, "private")
                        print(f"  [戳一戳] {'主人' if is_owner else '别人'}戳了{BOT_NAME} → {reply}", flush=True)
                continue

            # message: 收到消息（扔到线程池避免阻塞事件循环）
            if post_type == "message":
                msg_type = data.get("message_type", "")
                raw_msg = data.get("raw_message", "") or data.get("message", "")
                sender = data.get("sender", {})
                nickname = sender.get("nickname", "?") or sender.get("card", "?")

                if msg_type == "private":
                    uid = str(data.get("user_id", ""))
                    try:
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
        pass
    except Exception as e:
        import traceback
        print(f"  [WS异常] {e}", flush=True)
        traceback.print_exc()
    print(f"  [断开] {addr}", flush=True)

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
    print(f"\n  [超时] 等待超时，请手动确认 NapCat 运行正常后重启{BOT_NAME}")
    return False

# ==================== 启动 ====================
def main():
    print("=" * 44)
    print(f"  {BOT_NAME} · BaiYue  v3.0")
    print("  「我是 AI，但我懂你」")
    print(f"  NapCat API: {NAPCAT_HTTP}")
    print("=" * 44)
    print(f"  [调试] 伴侣模式={COMPANION_TYPE} | 自定义人格={'有' if CUSTOM_PROMPT_OWNER else '无'} | 私密模式={'开启' if PRIVATE_MODE else '关闭'}", flush=True)

    # 启动网页配置面板
    start_webui(8080)

    # 检查 API Key
    if not API_KEY and API_PROVIDER != "ollama":
        print("  [警告] 未设置 API Key，请在 WebUI 或 config.json 中填入")

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
        print(f"\n  {BOT_NAME}：下次见，拍档。")

if __name__ == "__main__":
    main()
