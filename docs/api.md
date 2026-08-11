# Agent HTTP 请求示例

QQ Bot 会替用户调用 Umamusume Agent。下面的请求用于联调或开发其他客户端。

```bash
export AGENT_URL=https://quantumxiaol-umamusume-agent.hf.space
export AGENT_API_KEY='替换为后端配置的 API_ACCESS_KEY'
```

所有受保护请求都需要：

```text
X-API-Key: <API_ACCESS_KEY>
```

请勿把真实 key 写入前端页面、公开仓库或浏览器 JavaScript。

## 状态和能力

服务状态位于根路径，不是 `/health`：

```bash
curl "$AGENT_URL/"
```

查询能力：

```bash
curl -H "X-API-Key: $AGENT_API_KEY" \
  "$AGENT_URL/capabilities"
```

当前云端支持对话 API v2、剧情事件、事件批次和导演模式；TTS 未启用。

## 角色列表

```bash
curl -H "X-API-Key: $AGENT_API_KEY" \
  "$AGENT_URL/characters"
```

## 创建单角色 session

`user_uuid` 应当是稳定 UUID。QQ Bot 使用 QQ OpenID 派生 UUID，不会把 OpenID 直接交给 Agent。

```bash
curl -X POST "$AGENT_URL/load_character" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "character_name": "爱慕织姬",
    "user_uuid": "00000000-0000-4000-8000-000000000001"
  }'
```

保存响应中的 `session_id`。

## 发送对白

```bash
curl -X POST "$AGENT_URL/chat" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "<SESSION_ID>",
    "message": "今天训练得很不错。",
    "generate_voice": false,
    "speaker": {
      "actor_id": "player",
      "actor_type": "trainer",
      "display_name": "训练员",
      "role_in_scene": "trainer"
    },
    "event_type": "dialogue"
  }'
```

## 发送动作

保持 `speaker` 为训练员，把 `event_type` 改成 `action`：

```json
{
  "message": "把毛巾递给她。",
  "event_type": "action"
}
```

## 发送环境事件

```json
{
  "message": "天空开始下起小雨。",
  "speaker": {
    "actor_id": "narrator",
    "actor_type": "narrator",
    "display_name": "环境",
    "role_in_scene": "environment"
  },
  "event_type": "scene_event"
}
```

## 一次发送连续事件

前置事件放入 `context_events`，最后一个事件仍放在普通 `message`、`speaker` 和
`event_type` 字段中：

```json
{
  "session_id": "<SESSION_ID>",
  "message": "要一起回去吗？",
  "event_type": "dialogue",
  "speaker": {
    "actor_id": "player",
    "actor_type": "trainer",
    "display_name": "训练员",
    "role_in_scene": "trainer"
  },
  "context_events": [
    {
      "content": "天空开始下雨。",
      "event_type": "scene_event",
      "speaker": {
        "actor_id": "narrator",
        "actor_type": "narrator",
        "display_name": "环境",
        "role_in_scene": "environment"
      }
    },
    {
      "content": "把伞撑开。",
      "event_type": "action",
      "speaker": {
        "actor_id": "player",
        "actor_type": "trainer",
        "display_name": "训练员",
        "role_in_scene": "trainer"
      }
    }
  ]
}
```

## 导演模式

查询预设：

```bash
curl -H "X-API-Key: $AGENT_API_KEY" \
  "$AGENT_URL/director/templates"
```

创建场景：

```bash
curl -X POST "$AGENT_URL/director/sessions" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "user_uuid": "00000000-0000-4000-8000-000000000001",
    "template_id": "tracen_training_ground_evening",
    "character_names": ["爱慕织姬", "无声铃鹿"],
    "story_outline": "训练结束后聊到下一场比赛"
  }'
```

推进一轮：

```bash
curl -X POST "$AGENT_URL/director/turn" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "<DIRECTOR_SESSION_ID>",
    "user_uuid": "00000000-0000-4000-8000-000000000001",
    "generate_voice": false,
    "events": [
      {
        "content": "今天大家都辛苦了。",
        "event_type": "dialogue",
        "speaker": {
          "actor_id": "player",
          "actor_type": "trainer",
          "display_name": "训练员",
          "role_in_scene": "trainer"
        }
      }
    ]
  }'
```

## 常见响应

- `401`：未提供 key 或 key 不一致。
- `404`：session 已过期或历史不存在，应重新创建并导入/恢复本地历史。
- `429`：触发后端限流，应稍后重试。
- `5xx`：模型提供商或后端暂时不可用。

