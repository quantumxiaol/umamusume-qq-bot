# Umamusume Agent QQ Bot

将 [Umamusume Agent](https://github.com/quantumxiaol/umamusume-agent) 接入 QQ 官方机器人。
当前版本使用 QQ WebSocket Gateway 接收群聊和私聊消息，并适配 Agent `0.2.0`
的 API key、结构化剧情事件、历史管理和多角色导演模式。Bot 使用本地 SQLite
保存恢复数据，即使 Hugging Face Space 重启并丢失临时文件，也能重建对话上下文。

## 当前连接方式

QQ 侧使用 WebSocket：

```text
QQ 开放平台 WebSocket Gateway
    ↓ 消息事件
qq-botpy
    ↓ HTTP API
Umamusume Agent
```

- QQ 管理后台的消息接收方式请选择 `WebSocket`。
- Bot 主动连接 QQ Gateway，不提供 Webhook，也不需要公网入站端口或回调 URL。
- [腾讯当前维护的 QQBot 文档](https://github.com/tencent-connect/openclaw-qqbot/blob/main/README.zh.md#webhook-传输模式)
  将 WebSocket 列为默认传输方式，并明确说明不需要公网 IP。
- QQ 消息回复仍由 SDK 调用 QQ OpenAPI HTTP 接口完成。

## 快速开始

### 1. 配置 `.env`

使用本地 Agent：

```env
AppID=你的QQ机器人AppID
AppSecret=你的QQ机器人AppSecret
UMAMUSEME_AGENT_URL=http://127.0.0.1:1111
UMAMUSEME_AGENT_API_ACCESS_KEY="与后端API_ACCESS_KEY相同的值"
LOG_LEVEL=INFO
BOT_DATABASE_PATH=data/bot.sqlite3
LOCAL_HISTORY_MAX_MESSAGES=1000
```

使用当前 Hugging Face Space：

```env
AppID=你的QQ机器人AppID
AppSecret=你的QQ机器人AppSecret
UMAMUSEME_AGENT_URL=https://quantumxiaol-umamusume-agent.hf.space
UMAMUSEME_AGENT_API_ACCESS_KEY="对应Space的API_ACCESS_KEY"
LOG_LEVEL=INFO
BOT_DATABASE_PATH=data/bot.sqlite3
LOCAL_HISTORY_MAX_MESSAGES=1000
```

Agent 设置了 `API_ACCESS_KEY` 时，Bot 会在所有受保护请求中发送 `X-API-Key`。
配置同时兼容以下别名：

- `UMAMUSUME_AGENT_URL`
- `AGENT_BASE_URL`
- `UMAMUSUME_AGENT_API_ACCESS_KEY`
- `AGENT_API_ACCESS_KEY`

其他可选配置：

- `AGENT_TIMEOUT_SECONDS`：默认 `600`
- `CHARACTERS_CACHE_TTL_SECONDS`：默认 `300`
- `LOG_LEVEL`：默认 `INFO`
- `BOT_DATABASE_PATH`：本地恢复数据库，默认 `data/bot.sqlite3`
- `LOCAL_HISTORY_MAX_MESSAGES`：每名用户、每个角色最多保留的本地消息数，默认 `1000`；设为
  `0` 表示不限制

### 2. 启动

如果使用本地 Agent，先启动后端：

```bash
uvicorn umamusume_agent.server.dialogue_server:app \
  --host 127.0.0.1 \
  --port 1111
```

然后在本项目根目录启动 Bot：

```bash
uv run umamusume-qq-bot
```

也可以使用：

```bash
PYTHONPATH=src .venv/bin/python -m umamusume_qq_bot
python main.py
```

日志写入 `logs/bot.log`。出现 `QQ bot ready` 表示 WebSocket Gateway 已连接成功。
首次启动会自动创建 `data/bot.sqlite3`，无需安装或启动独立数据库服务。

安装依赖后，也可以绕过常驻的 `uv run` 父进程，直接启动以进一步节省内存：

```bash
uv sync --frozen --no-dev
.venv/bin/umamusume-qq-bot
```

如果所在网络必须使用 HTTP 代理，可选用：

```bash
uv run umamusume-qq-bot-proxy --proxy http://127.0.0.1:10808
```

代理启动器只是网络故障排查工具，正常 WebSocket 接入不需要代理、固定公网 IP 或旧版
IP 白名单配置。

## QQ 使用方式

群聊中需要 `@机器人`，好友私聊可直接发送。

### 通用命令

```text
帮助
服务状态
单角色模式
导演模式
```

`服务状态` 会显示 Agent 版本、对话 API 版本、导演模式和 TTS 能力。

### 单角色模式

```text
角色列表
切换角色
切换角色 <角色名或编号>
当前角色
查看记录
清空记录 确认
重新生成
编辑上一句 <新内容>
```

选定角色后，直接发送文字就是训练员对白。Bot 会在 Agent session 过期时自动重新加载角色并恢复历史。

### 剧情事件

与当前 Agent 前端一致，QQ Bot 支持三种输入：

```text
对白 今天就练到这里吧。
动作 把毛巾递给她。
环境 夜幕降临，训练场开始下起小雨。
```

还可以先把多条事件加入队列，让它们在一次模型调用中形成完整上下文：

```text
加入动作 把毛巾放在长椅上。
加入环境 训练场的灯亮了起来。
待发送
发送 今天就练到这里吧。
```

相关命令：

```text
加入对白 <内容>
加入动作 <内容>
加入环境 <内容>
待发送
清空待发送
发送 <最后一句对白>
```

仅发送 `发送` 时，队列的最后一条事件会作为本轮最终事件。

### 多角色导演模式

进入导演模式：

```text
导演模式
场景列表
```

使用预设场景：

```text
创建场景 1 | 爱慕织姬,无声铃鹿 | 训练结束后偶遇，逐渐聊到下一场比赛
```

使用简化的自定义场景：

```text
创建自定义场景 雨后的河边 | 爱慕织姬,无声铃鹿 | 河边散步 | 训练后放松交谈
```

场景创建后，直接发送文字，或使用 `对白`、`动作`、`环境` 和事件队列。导演会维护共享场景状态，
并安排一至多位角色回应。

导演模式命令：

```text
导演状态
场景历史
恢复场景 <编号>
重新生成
结束场景
删除场景记录 <编号> 确认
导演帮助
单角色模式
```

Bot 会同时在内存和本地 SQLite 中保存导演场景快照。当 Agent session 过期时，会依次尝试后端
历史恢复和本地快照恢复。Bot 自身或 Hugging Face Space 重启后，仍可使用本地 `场景历史`
恢复。

## 与 Agent 前端的功能对应

| Agent 前端能力 | QQ Bot |
| --- | --- |
| 角色选择与历史恢复 | 支持 |
| JSON v2 动作/对白 | 支持，并兼容旧 `reply` |
| 对白/动作/环境事件 | 支持 |
| 多事件批量上下文 | 支持 |
| 查看与清空历史 | 支持 |
| 编辑上一句/重新生成 | 支持 |
| 导演预设场景 | 支持 |
| 导演自定义场景 | 支持简化文本格式 |
| 多角色导演对话 | 支持 |
| 导演历史恢复/删除 | 支持 |
| 导演最后回复重生成 | 支持 |
| 浏览器缓存恢复 | 使用服务器本地 SQLite 实现等价恢复能力 |
| 浏览器文件导入导出 | 不适用于纯文本 QQ 命令 |
| TTS 播放 | 根据后端能力检测；当前云端未启用 |

## 用户身份与历史

- 群聊使用 `member_openid`，私聊使用 `user_openid`。
- Bot 将 QQ 用户标识通过 `uuid5` 转换为稳定 `user_uuid`。
- 单角色消息成功返回后会写入本地 SQLite；Agent session 或远端文件丢失时，通过
  `/history/import` 自动恢复。
- 导演场景按相同 `user_uuid` 隔离，并在每次创建、推进、恢复和重新生成后保存完整公开快照。
- 当前角色、交互模式、待发送事件和活动场景也会落盘，Bot 重启后可以继续使用。
- `清空记录 确认` 和 `删除场景记录 <编号> 确认` 会同时删除远端与本地副本。

数据库包含用户 OpenID 对应标识和对话正文，应按敏感数据保护。SQLite 使用 WAL 模式，备份时
建议先停止 Bot，然后复制整个 `data` 目录。

## 低内存服务器部署

仅在服务器运行 QQ Bot、Agent 使用 Hugging Face Space 时，不需要部署 FastAPI、模型或独立
数据库。Bot Python 进程实测约 `39 MB`；直接运行 `.venv/bin/umamusume-qq-bot` 时不会保留
额外的 `uv run` 父进程。300 MB 空闲内存足够这种模式。

如果使用 Docker，必须把 `data` 目录挂载到宿主机或持久卷，例如：

```text
/opt/umamusume-qq-bot/data  ->  /app/data
```

否则删除或重建容器时，本地恢复数据库也会被删除。普通 VPS 直接在固定工作目录运行时，默认
`data/bot.sqlite3` 会正常保留。

## 开发与测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

核心实现：

- `agent_client.py`：Agent HTTP API、鉴权及协议兼容
- `dialogue_commands.py`：剧情事件命令协议
- `bot_client.py`：QQ 事件和命令路由
- `state_store.py`：内存状态及持久化接口
- `persistence.py`：本地 SQLite 状态、单角色历史和导演快照
