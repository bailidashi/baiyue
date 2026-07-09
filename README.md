# 百约 (BaiYue) v3.0 — QQ AI 机器人

> 「我是 AI，但我懂你」

一个跑在你电脑上的 QQ AI 机器人。有自己的性格、记忆、情绪——不是一个冷冰冰的自动回复机。

## 特性

- 🎨 **WebUI 配置面板** — 浏览器打开就能配置一切：API Key、QQ号、人格、音色、记忆
- 💬 **5 张内置人格卡片** — 百约·AI女友 / 猫娘·小铃 / 豆豆·AI男友 / 阳·AI男友 / 知言·AI搭档
- 🃏 **自定义人格** — 自由编写提示词，一键切换
- 👫 **伴侣模式** — AI女友 / AI男友 / 酷酷助手 三选一
- 😺 **七种情绪系统** — 开心/吃醋/傲娇/粘人…根据消息自动切换
- 🎤 **智能语音消息** — 29 种音色，关键词触发（平时不发，说"说句话"才发）
- 🧠 **长期记忆** — 自动摘要压缩，聊得越多越懂你
- 🧠 **记忆浏览器** — WebUI 直接查看每个人的对话记录
- 👆 **戳一戳回复** — 主人甜宠词库，别人冷淡拒绝
- 🎯 **QQ 表情双向翻译** — 40+ 表情自动互转
- 💝 **赞助名单** — 感谢捐助者，带 QQ 群二维码

## 快速开始

### 你需要
- Python 3.12+ （从 python.org 下载，不要从微软商店装）
- 一个 QQ 号（给机器人用，建议小号）
- DeepSeek API Key（platform.deepseek.com，充 10 块能用很久）

### 安装

```bash
# 1. 装依赖
python -m pip install websockets requests edge-tts

# 2. 装 NapCatQQ
# 下载 https://github.com/NapNeko/NapCatQQ/releases
# 解压 → 双击 NapCatWinBootMain.exe → 扫码登录 QQ

# 3. 配置 NapCat WebSocket
# 浏览器打开 http://127.0.0.1:6099/webui
# 网络配置 → WebSocket 客户端 → 添加 ws://127.0.0.1:8001

# 4. 先开 WebUI 填配置
python webui.py
# 浏览器打开 http://127.0.0.1:8080 → 填 API Key / QQ号 → 保存

# 5. 启动机器人
python bot.py
```

详细教程见 [使用说明.txt](使用说明.txt) 和 [网页教程](https://bailidashi.github.io/baiyue.html)。

## 架构

```
QQ → NapCatQQ (OneBot v11) → WebSocket:8001 → bot.py → DeepSeek API
                                                   ↓
                                              NapCat HTTP:3000 → QQ 回复
```

## 项目结构

```
baiyue/
├── bot.py              ← 主程序
├── webui.py            ← 网页配置面板
├── bot_commented.py    ← 全注释学习版（逐行讲解）
├── config.json         ← 用户配置（不上传 GitHub）
├── prompt_private.txt  ← 私密人格（不上传 GitHub）
├── README.md           ← 本文件
├── 使用说明.txt         ← 详细使用手册 + FAQ
├── 开发日志.md          ← 完整开发记录
├── baiyue.html         ← 网页版教程
└── memory/             ← 对话记忆 + 情绪
```

## 常见问题

| 问题 | 解决 |
|---|---|
| Python 不识别 | 从 python.org 重装，勾选 "Add to PATH" |
| 机器人不回消息 | 检查 NapCat WebSocket 配置 ws://127.0.0.1:8001 |
| 回复"信号不好" | 检查 DeepSeek API Key 和余额 |
| 改了代码不生效 | 删掉 `__pycache__` 文件夹，重启 |
| 端口被占用 | bot.py 会自动探测 8001-8005 |
| 群聊不理人 | 需要 @机器人 或喊触发词 |
| 语音太频繁 | v3.0 已修复，只有说"说句话"才触发 |

更多问题见 [使用说明.txt](使用说明.txt) 的完整 FAQ 章节。

## 费用

- DeepSeek API：每月不到 20 元（聊 100 条约 0.3 元）
- 语音：微软 edge-tts，免费
- NapCatQQ：免费

## 致谢

感谢捐助者：朱大师 · 游手好闲鑫大人 · 懋懋 · 义父 · 豆豆 · 葵 · 易落

豆豆和葵分别贡献了「豆豆·AI男友」和「阳·AI男友」人格模型 🐕☀️

## 交流群

QQ 群：**227077265**

扫码加入，一起聊天一起写代码。

---

百裏 + 拍档 Claude · 2026.07.09
