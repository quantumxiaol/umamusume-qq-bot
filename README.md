# Umamusume Agent QQ Bot Server

[Umamusume Agent](https://github.com/quantumxiaol/umamusume-agent)

## QQ Bot 快速开始

### 1) 环境变量

在 `.env` 中至少配置：

```env
AppID=你的QQ机器人AppID
AppSecret=你的QQ机器人AppSecret
UMAMUSEME_AGENT_URL=http://127.0.0.1:1111
LOG_LEVEL=INFO
```

可选参数：

- `UMAMUSUME_AGENT_URL`（兼容别名）
- `AGENT_BASE_URL`（旧配置名，向后兼容）
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

本地代理测试（无公网白名单 IP 时）：

```bash
# 方式1：使用环境变量
export HTTPS_PROXY=http://127.0.0.1:10808
export HTTP_PROXY=http://127.0.0.1:10808
uv run umamusume-qq-bot-proxy

# 方式2：命令行显式指定
uv run umamusume-qq-bot-proxy --proxy http://127.0.0.1:10808

# 仅检查代理参数解析，不真正启动
uv run umamusume-qq-bot-proxy --proxy http://127.0.0.1:10808 --check-only

# 打开代理调试日志（打印每个 QQ 域名请求是否注入 proxy）
QQBOT_PROXY_DEBUG=1 uv run umamusume-qq-bot-proxy --proxy http://127.0.0.1:10808
```

说明：
- `umamusume-qq-bot-proxy` 仅用于本地调试。它会在启动前 monkey patch `aiohttp.ClientSession`，为 QQ 平台域名请求强制注入代理，并启用 `trust_env=True`，不修改 `botpy` 源码。
- 生产部署到公网固定 IP 后，直接使用 `uv run umamusume-qq-bot` 即可。

公网固定 IP 部署启动（推荐线上）：

```bash
# 1) 确保 QQ 平台 IP 白名单已加入服务器公网出口 IP
# 2) 线上环境建议不要设置代理
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

# 3) 先启动 agent（同机部署示例）
uvicorn umamusume_agent.server.dialogue_server:app --host 127.0.0.1 --port 1111

# 4) 启动 QQ Bot（无需 proxy runner）
uv run umamusume-qq-bot
```

说明：
- 线上建议 `UMAMUSEME_AGENT_URL` 使用内网或本机地址（如 `http://127.0.0.1:1111`）。
- 该 bot 为主动出网连接 QQ 网关，一般不需要额外开放入站端口给 bot 本体。

白名单与代理出口 IP 排查：

```bash
# 1) 让 .env 生效
set -a
source .env
set +a

# 2) 指定本地代理
PROXY="http://127.0.0.1:10808"

# 3) 通过代理查看当前出口 IP（把该 IP 加到 QQ 平台白名单）
curl -sS -x "$PROXY" https://4.ipw.cn
curl -sS -x "$PROXY" https://ifconfig.me

# 4) 用 AppID + AppSecret 换取 access_token
TOKEN_JSON="$(curl -sS -x "$PROXY" https://bots.qq.com/app/getAppAccessToken \
  -H 'Content-Type: application/json' \
  --data-raw "{\"appId\":\"$AppID\",\"clientSecret\":\"$AppSecret\"}")"
echo "$TOKEN_JSON"
ACCESS_TOKEN="$(printf '%s' "$TOKEN_JSON" | python -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""), end="")' | tr -d '\r\n')"

# 5) 用 access_token 验证 /users/@me
curl -sS -x "$PROXY" https://api.sgroup.qq.com/users/@me \
  -H "Authorization: QQBot ${ACCESS_TOKEN}" \
  -H "X-Union-Appid: ${AppID}" \
  -w '\nStatus: %{http_code}\n'
```

结果解释：
- 返回机器人信息（通常 HTTP 200）表示鉴权与白名单通过。
- 返回 `11298 接口访问源IP不在白名单` 表示代理出口 IP 还未加入白名单，或代理在切换出口 IP。
- 返回 `11241 请求头Authorization参数格式错误` 通常表示 `ACCESS_TOKEN` 为空或包含异常字符（换行/引号）。
- `.env` 里的 `Token` 字段不是这个新鉴权流程的必需项，建议以 `AppID + AppSecret` 实时换取 token 为准。

### 3) 群聊内使用方式

把机器人拉进群后，群友 `@机器人`：

- 发送 `角色列表`：查看并进入角色选择模式
- 发送 `切换角色`：重新选择角色
- 发送 `当前角色`：查看当前角色
- 发送 `编号` 或 `角色名`：确定角色
- 已选角色后，直接 `@机器人 + 文字`：进入角色对话

### 4) 好友私聊使用方式

添加机器人好友后，直接发送消息即可（不需要 `@`）：

- 发送 `角色列表`：查看并进入角色选择模式
- 发送 `切换角色`：重新选择角色
- 发送 `当前角色`：查看当前角色
- 发送 `编号` 或 `角色名`：确定角色
- 已选角色后，直接发送文字：进入角色对话

用户记忆说明：

- Bot 会使用 QQ 侧用户稳定标识（群聊 `member_openid` / 好友 `user_openid`）生成固定 UUID（`uuid5`）作为 `user_uuid`。
- 每次切换角色时都会将该 `user_uuid` 传给 `umamusume-agent` 的 `/load_character`，从而按“同一用户 + 同一角色”恢复历史。

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
