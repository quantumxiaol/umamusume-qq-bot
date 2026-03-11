# Umamusume Agent QQ Bot Server

[Umamusume Agent](https://github.com/quantumxiaol/umamusume-agent)

## QQ Bot 快速开始

### 1) 环境变量

在 `.env` 中至少配置：

```env
AppID=你的QQ机器人AppID
AppSecret=你的QQ机器人AppSecret
AGENT_BASE_URL=http://127.0.0.1:1111
LOG_LEVEL=INFO
```

可选参数：

- `AGENT_TIMEOUT_SECONDS`（默认 `20`）
- `CHARACTERS_CACHE_TTL_SECONDS`（默认 `300`）

### 2) 启动 Bot

先启动你的 `umamusume-agent` 服务，再启动 QQ Bot。

推荐命令（项目根目录）：

```bash
uv run umamusume-qq-bot
```

等价命令（任选其一）：

```bash
PYTHONPATH=src .venv/bin/python -m umamusume_qq_bot
python main.py
```

启动成功后日志会输出到 `logs/bot.log`，并可看到类似 `QQ bot ready` 的日志。

### 3) 群聊内使用方式

把机器人拉进群后，群友 `@机器人`：

- 发送 `角色列表`：查看并进入角色选择模式
- 发送 `切换角色`：重新选择角色
- 发送 `当前角色`：查看当前角色
- 发送 `编号` 或 `角色名`：确定角色
- 已选角色后，直接 `@机器人 + 文字`：进入角色对话

## Umamusume Agent接口简述

- `POST /load_character`：加载角色并创建会话
- `POST /chat`：非流式对话
- `POST /chat_stream`：流式对话（SSE）
- `GET /characters`：可用角色列表
- `GET /audio?path=...`：音频文件访问

### 对话请求参数（`/chat` 与 `/chat_stream`）

- `session_id`：会话 ID（由 `/load_character` 返回）
- `message`：用户输入文本
- `generate_voice`：是否生成语音（默认 `false`）
- `text_only`：是否纯文本模式（默认 `false`）

参数组合说明：
- `generate_voice=false, text_only=false`：结构化文本回复（通常含“动作/对白”标签），不生成语音。
- `generate_voice=true, text_only=false`：结构化文本回复，并触发 TTS 生成语音。
- `text_only=true`：纯文本回复（无“动作/对白”标签），并强制不生成语音（即使 `generate_voice=true` 也会忽略）。

### 会话生命周期与内存控制

- 会话通过内存字典管理（`session_id -> session`）。
- 每条消息会刷新会话活跃时间；超出 `DIALOGUE_SESSION_TTL_SECONDS` 的空闲会话会被清理。
- 服务启动后会有后台任务按 `DIALOGUE_SESSION_CLEANUP_INTERVAL_SECONDS` 周期扫描并删除过期会话。
- 对话历史会按 `DIALOGUE_SESSION_HISTORY_MAX_MESSAGES` 自动裁剪，避免单会话无限增长。
- 会话过期或被删除后，再用旧 `session_id` 调用 `/chat` 会返回 `404`，需要重新 `/load_character` 获取新会话。

## 无前端：纯文本模式如何选定角色

核心逻辑：角色是通过 `POST /load_character` 绑定到 `session_id` 的。后续 `/chat` 只需要传这个 `session_id`。

### 1) 查看可用角色（可选）

```bash
curl -s http://127.0.0.1:1111/characters
```

### 2) 选定角色并创建会话

```bash
curl -s -X POST http://127.0.0.1:1111/load_character \
  -H "Content-Type: application/json" \
  -d '{"character_name":"爱慕织姬"}'
```

返回里拿到 `session_id`，例如：

```json
{
  "session_id": "0f0f7f4f-xxxx-xxxx-xxxx-8b0b5f9a8d2b",
  "character_name": "爱慕织姬"
}
```

### 3) 用该会话进行纯文本对话

```bash
curl -s -X POST http://127.0.0.1:1111/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id":"0f0f7f4f-xxxx-xxxx-xxxx-8b0b5f9a8d2b",
    "message":"你好，今天训练安排是什么？",
    "text_only":true
  }'
```

如果想切换角色，重新调用一次 `/load_character` 获取新的 `session_id` 即可。

### 4) 示例
```bash
(umamusume-agent)  umamusume-agent % curl -s -X POST http://127.0.0.1:1111/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id":"4863e6ed-d",
    "message":"你好，今天训练安排是什么？",
    "text_only":false
  }'
{"reply":"动作：抬起头，耳朵轻微抖动，目光直视训练员  \n对白：今天的训练计划我已经看过了。如果可以，我想增加一些长距离的耐力训练。我必须得多加训练，赢得比赛，绝对要成为那闪耀的一等星。你觉得这样安排如何？"}%                                             
(umamusume-agent) umamusume-agent % curl -s -X POST http://127.0.0.1:1111/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id":"4863e6ed-d",
    "message":"我刚才问你什么了？", 
    "text_only":false
  }'
{"reply":"动作：耳朵轻轻向后压，眼神略显不耐却又藏着一丝无奈  \n对白：你刚才问了我今天的训练安排。既然你选择了我，这些基本的事情，你应该记得吧。"}% 
```
