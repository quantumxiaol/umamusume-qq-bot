# 架构与历史恢复

## 连接方式

```text
QQ 私聊 / 群聊 @
        ↓ WebSocket 事件
qq-botpy Client
        ↓ 命令解析与用户状态
Umamusume QQ Bot
        ├── HTTPS + X-API-Key → Umamusume Agent
        └── SQLite → 本地历史与场景快照
```

QQ 管理后台应选择 WebSocket。Bot 主动连接 QQ Gateway，不提供 Webhook，也不需要公网入站端口、
回调 URL 或旧版 IP 白名单。回复消息仍由 SDK 调用 QQ OpenAPI HTTP 接口完成。

## 用户身份

- 群聊使用 `member_openid`。
- 私聊使用 `user_openid`。
- Bot 使用 UUID v5 将 QQ 标识转换为稳定 `user_uuid`。
- Agent 和 SQLite 均按 `user_uuid` 隔离历史。
- QQ OpenID、派生 UUID 和对话正文均属于需要保护的数据。

## 输入协议

| QQ 输入 | actor | event_type |
| --- | --- | --- |
| 普通文字 / `对白` | trainer | `dialogue` |
| `动作` | trainer | `action` |
| `环境` | narrator | `scene_event` |

事件队列中，前置事件写入 `context_events`，最后一条作为普通 `/chat` 请求字段。一次批次只触发一次
模型生成。

## 本地 SQLite

`data/bot.sqlite3` 包含三类数据：

| 表 | 内容 |
| --- | --- |
| `user_states` | 当前角色、模式、session ID、事件队列、活动导演快照 |
| `single_messages` | 可重新导入 Agent 的单角色用户与助手消息 |
| `director_snapshots` | 每个导演 session 的完整公开场景快照 |

数据库使用 WAL 与 `synchronous=NORMAL`，文件权限会尝试设置为 `0600`。

## 单角色恢复

```text
正常 /chat
  → Agent 返回角色回复
  → 本地原子追加用户事件与助手回复

session 404
  → /load_character 创建新 session
  → 比较 Agent 历史与本地历史
  → Agent 完整：同步到本地
  → Agent 丢失/不完整：清理残留并 /history/import 本地副本
  → 重试 /chat
```

首次启用本地数据库时，用户重新选择角色即可把仍存在于 HF 的旧历史同步到本地。

## 导演模式恢复

每次创建、推进、恢复和重新生成场景后，Bot 都保存完整公开快照。

```text
导演 turn 返回 404
  → 尝试恢复 Agent JSONL 历史
  → 仍为 404：使用本地 snapshot 调用 /director/sessions/recover
  → 重试本轮事件
```

`场景历史` 会合并本地与 Agent 记录。本地记录优先显示，避免 HF 已有大量旧记录时隐藏本地场景。

## 能力对应

| Agent 能力 | QQ Bot |
| --- | --- |
| 对话 API v2 动作/对白 | 支持，并兼容旧文本响应 |
| 对白、动作、环境事件 | 支持 |
| 多事件批量上下文 | 支持 |
| 查看、清空、导入历史 | 支持 |
| 编辑上一句、重新生成 | 支持 |
| 导演预设与自定义场景 | 支持 |
| 1–3 名导演角色 | 支持 |
| 导演历史恢复与删除 | 支持 |
| 导演最后回复重新生成 | 支持 |
| 浏览器 localStorage 恢复 | 以服务器 SQLite 实现等价能力 |
| TTS | 按后端能力检测；当前 HF 未启用 |

## 核心模块

- `agent_client.py`：HTTP、API key、Agent 协议与错误转换
- `dialogue_commands.py`：QQ 文本到剧情事件的解析
- `bot_client.py`：私聊/群聊处理、命令路由、恢复流程
- `state_store.py`：ConversationState 与统一存储接口
- `persistence.py`：SQLite schema 和持久化操作

