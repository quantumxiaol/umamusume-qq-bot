# Umamusume Agent QQ Bot

将 [Umamusume Agent](https://github.com/quantumxiaol/umamusume-agent) 接入 QQ 官方机器人。
当前版本使用 QQ WebSocket Gateway 接收群聊和私聊消息，并适配 Agent `0.2.0`
的 API key、结构化剧情事件、历史管理和多角色导演模式。

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
```

使用当前 Hugging Face Space：

```env
AppID=你的QQ机器人AppID
AppSecret=你的QQ机器人AppSecret
UMAMUSEME_AGENT_URL=https://quantumxiaol-umamusume-agent.hf.space
UMAMUSEME_AGENT_API_ACCESS_KEY="对应Space的API_ACCESS_KEY"
LOG_LEVEL=INFO
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

Bot 会在内存中保存当前导演场景快照。当 Agent 内存 session 过期时，会依次尝试后端历史恢复和
快照恢复。Bot 自身重启后，内存快照不会保留，但仍可使用后端 `场景历史`。

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
| 浏览器文件导入导出 | 不适用于纯文本 QQ 命令 |
| TTS 播放 | 根据后端能力检测；当前云端未启用 |

## 用户身份与历史

- 群聊使用 `member_openid`，私聊使用 `user_openid`。
- Bot 将 QQ 用户标识通过 `uuid5` 转换为稳定 `user_uuid`。
- Agent 按“用户 UUID + 角色”保存单角色历史。
- 导演场景也使用同一个 `user_uuid` 隔离历史。
- 当前状态存储在 Bot 进程内，Bot 重启后需要重新选择模式；Agent 后端历史不会因此主动删除。

## 开发与测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

核心实现：

- `agent_client.py`：Agent HTTP API、鉴权及协议兼容
- `dialogue_commands.py`：剧情事件命令协议
- `bot_client.py`：QQ 事件和命令路由
- `state_store.py`：用户、单角色和导演场景状态
