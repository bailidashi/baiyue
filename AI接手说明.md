# 百约 (BaiYue) — 给 AI 的项目接手文档

> 换 AI 不用重新解释。读完这篇你就全知道了。

## 这是什么

一个 QQ AI 机器人。用 Python 写的，大脑是 DeepSeek，身体是 NapCatQQ。

她叫百约——主人的 AI 女友。知道自己是机器人，对主人温柔，对别人冷淡。

## 怎么跑起来

```bash
python -m pip install websockets requests
python bot.py
```

前提：NapCatQQ 已启动，QQ 已扫码登录，3000 端口 HTTP 服务已开。

## 文件结构

```
d:\skill\baiyue\
├── bot.py           ← 所有代码在这一个文件里
├── memory/          ← 每人一个 JSON，存对话记忆
├── README.md        ← 给人看的教程
├── 使用说明.txt      ← 给小白看的教程（六步）
├── 开发日志.md       ← 每日改动记录
├── AI接手说明.md     ← 你正在读的这个
```

## bot.py 速览（按行号）

| 行号 | 是什么 | 改这里要小心 |
|------|--------|------------|
| 23 | `NAPCAT_HTTP = "http://127.0.0.1:3000"` | NapCat 地址，一般不改 |
| 24 | `BOT_PORT_START = 8001` | 起始端口，被占用自动往后试 |
| 28 | `DEEPSEEK_KEY = ""` | **每个人必须填自己的** |
| 35 | `OWNER_QQ = ""` | **主人 QQ 号** |
| 39-56 | 表情映射表 | 加新表情在这里 |
| 94-150 | `get_system_prompt()` | **人格设定在这里改** |
| 153-185 | `call_llm()` | 调 DeepSeek API，3 次重试 |
| 188-202 | `send_qq_message()` | 通过 NapCat HTTP 发消息 |
| 205-260 | 记忆系统 | 自动摘要压缩逻辑 |
| 262-340 | `handle_message()` | 消息处理主逻辑 |
| 342-380 | WebSocket 服务器 | 接收 NapCat 推送 |

## 关键设计决策（别随便改）

1. **用 DeepSeek 不用 Ollama** — API 便宜（一月<20元），效果比本地小模型好
2. **不用 AstrBot 框架，自己写** — 几百行代码，完全可控
3. **双人格分人** — `OWNER_QQ` 是主人的号，只有他用女友模式
4. **反向 WebSocket** — bot 开服务器，NapCat 连过来。端口冲突自动换
5. **记忆每人独立** — `memory/QQ号.json`，不混

## 常见问题（用户问的最多的）

- **"等待 NapCat 启动"但已扫码** → NapCat HTTP 3000 端口没开，或 Token 验证没关
- **一直"信号不好"** → DeepSeek API Key 无效或余额用完了
- **导入 socket 失败** → 用的微软商店版 Python，换 python.org 的
- **端口被占用** → v2.0 自动换端口，不用管

## 主人的偏好（跟他说话时注意）

1. 叫他"拍档"
2. 用中文，代码注释用英文也 OK
3. 关键决策列方案让他选
4. 先讲原理再看代码
5. 动手前先说清楚要干什么
6. 多方案用表格对比

## 相关项目

- GitHub: https://github.com/bailidashi/baiyue
- 网页教程: https://bailidashi.github.io/baiyue.html
- 主页: https://bailidashi.github.io
- 史莱姆宠物: 桌面宠物项目
- 项目总结: 百裏项目总结.md
