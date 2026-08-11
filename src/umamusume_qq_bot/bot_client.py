from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import botpy
from botpy.message import C2CMessage, GroupMessage

from .agent_client import (
    AgentClient,
    AgentError,
    AgentHttpError,
    AgentSessionExpiredError,
    LoadCharacterResult,
)
from .config import Settings
from .dialogue_commands import (
    build_dialogue_event,
    dialogue_event_fields,
    event_for_request,
    format_queued_events,
    input_mode_from_history,
    parse_direct_event,
    parse_queue_event,
)
from .state_store import ConversationState, ConversationStore
from .text_utils import (
    format_character_choices,
    normalize_group_text,
    resolve_character_selection,
    truncate_reply,
)

LOGGER = logging.getLogger(__name__)

DOCS_URL = "https://quantumxiaol.github.io/umamusume-qq-bot/"

COMMAND_GUIDE_TEXT = (
    "常用命令：\n"
    "角色列表｜切换角色 <名称或编号>｜当前角色\n"
    "查看记录｜重新生成｜编辑上一句 <新内容>\n"
    "导演模式｜单角色模式｜服务状态"
)

DIRECTOR_GUIDE_TEXT = (
    "导演模式帮助：\n"
    "1. 发送「场景列表」查看预设。\n"
    "2. 创建场景：\n"
    "创建场景 1 | 爱慕织姬,东海帝皇 | 午后偶遇\n"
    "3. 创建后可直接对话，也可发送「动作/环境 <内容>」。\n"
    "管理：导演状态｜场景历史｜恢复场景 <编号>｜重新生成｜结束场景\n"
    "自定义：创建自定义场景 <地点> | <角色1,角色2> | <场景名> | <剧情大纲>\n"
    f"完整手册：{DOCS_URL}#director"
)

WELCOME_TEXT = (
    "你好，我是赛马娘角色对话机器人。\n"
    "普通文字默认是对白；也可以用「动作」和「环境」推动剧情。\n"
    "发送「帮助」查看命令，发送「文档」打开完整手册。"
)

HELP_TEXT = (
    "使用帮助：\n"
    "1.「角色列表」→ 回复编号或名称 → 直接聊天。\n"
    "2. 普通文字是对白；也可发送「动作 <内容>」「环境 <内容>」。\n"
    "3. 多角色剧情发送「导演模式」。\n"
    f"{COMMAND_GUIDE_TEXT}\n"
    "分主题：单角色帮助｜事件帮助｜导演帮助｜历史帮助\n"
    "群聊需 @我，好友私聊可直接发送。\n"
    f"完整手册：{DOCS_URL}"
)

SINGLE_GUIDE_TEXT = (
    "单角色模式帮助：\n"
    "角色列表｜切换角色 <名称或编号>｜当前角色\n"
    "选择后直接发送文字即可对话。\n"
    "重新生成｜编辑上一句 <新内容>\n"
    "查看记录｜清空记录 确认\n"
    f"完整手册：{DOCS_URL}#start"
)

EVENT_GUIDE_TEXT = (
    "剧情事件帮助：\n"
    "对白 <内容>：训练员说出的话；普通文字也是对白。\n"
    "动作 <内容>：训练员做出的行为。\n"
    "环境 <内容>：天气、声音或场景变化。\n"
    "可用空格或冒号，例如「动作：望向窗外」。\n"
    "组合一轮：先发送「加入动作/环境 <内容>」，再发送「发送 <最后一句>」。\n"
    "查看队列：待发送｜清空待发送\n"
    f"完整手册：{DOCS_URL}#events"
)

HISTORY_GUIDE_TEXT = (
    "历史记录帮助：\n"
    "查看记录：显示当前角色最近的消息。\n"
    "清空记录 确认：删除当前角色的本地和远端历史。\n"
    "场景历史：查看导演场景；恢复场景 <编号> 可继续。\n"
    "Bot 会把历史保存在服务器 SQLite 中，HF 会话失效后可自动恢复。\n"
    f"完整手册：{DOCS_URL}#storage"
)


class UmamusumeBotClient(botpy.Client):
    def __init__(self, settings: Settings, agent_client: AgentClient, state_store: ConversationStore):
        intents = botpy.Intents.none()
        intents.public_messages = True
        super().__init__(intents=intents, bot_log=None, ext_handlers=False)
        self._settings = settings
        self._agent = agent_client
        self._store = state_store

    async def close(self) -> None:
        await self._agent.close()
        self._store.close()
        await super().close()

    async def on_ready(self):
        LOGGER.info("QQ bot ready: name=%s id=%s", self.robot.name, self.robot.id)

    async def on_group_at_message_create(self, message: GroupMessage):
        group_openid = message.group_openid or ""
        member_openid = getattr(message.author, "member_openid", "") or ""
        text = normalize_group_text(message.content or "")

        LOGGER.info(
            "group_at_message group=%s member=%s msg_id=%s text=%r",
            group_openid,
            member_openid,
            message.id,
            text,
        )

        if not group_openid or not member_openid:
            await message.reply(content="无法识别当前会话身份，请稍后重试。")
            return

        response = await self._safe_handle_user_input(
            user_identity=member_openid,
            text=text,
            log_context=f"group={group_openid} member={member_openid}",
        )
        await message.reply(content=truncate_reply(response))

    async def on_c2c_message_create(self, message: C2CMessage):
        user_openid = getattr(message.author, "user_openid", "") or ""
        text = normalize_group_text(message.content or "")

        LOGGER.info("c2c_message user=%s msg_id=%s text=%r", user_openid, message.id, text)

        if not user_openid:
            await message.reply(content="无法识别当前会话身份，请稍后重试。")
            return

        response = await self._safe_handle_user_input(
            user_identity=user_openid,
            text=text,
            log_context=f"user={user_openid}",
        )
        await message.reply(content=truncate_reply(response))

    async def _safe_handle_user_input(
        self,
        user_identity: str,
        text: str,
        log_context: str,
    ) -> str:
        try:
            return await self._handle_user_input(user_identity=user_identity, text=text)
        except AgentError as exc:
            LOGGER.warning("Agent request failed %s: %s", log_context, exc)
            return "对话服务暂时不可用，请稍后重试。"
        except Exception:
            LOGGER.exception("Unexpected error while handling message %s", log_context)
            return "处理消息时发生错误，请稍后重试。"

    async def _handle_user_input(self, user_identity: str, text: str) -> str:
        state = self._store.get(user_identity=user_identity)
        normalized = text.strip()
        first_interaction = not state.has_seen_welcome
        if first_interaction:
            state.has_seen_welcome = True

        try:
            response = await self._dispatch_input(state, normalized)
            if first_interaction:
                return f"{WELCOME_TEXT}\n\n{response}"
            return response
        finally:
            state.updated_at = datetime.now().timestamp()
            self._store.save(state)

    async def _dispatch_input(self, state: ConversationState, normalized: str) -> str:
        if normalized in {"帮助", "help", "/help"}:
            return HELP_TEXT
        if normalized in {"单角色帮助", "单人帮助", "帮助 单角色", "帮助 单人"}:
            return SINGLE_GUIDE_TEXT
        if normalized in {"事件帮助", "剧情帮助", "帮助 事件", "帮助 剧情"}:
            return EVENT_GUIDE_TEXT
        if normalized in {"导演帮助", "场景帮助"}:
            return DIRECTOR_GUIDE_TEXT
        if normalized in {"历史帮助", "记录帮助", "帮助 历史", "帮助 记录"}:
            return HISTORY_GUIDE_TEXT
        if normalized in {"文档", "使用手册", "在线文档", "教程"}:
            return f"完整使用手册：\n{DOCS_URL}"
        if normalized in {"服务状态", "后端状态", "status"}:
            return await self._show_service_status(state)
        if normalized in {"单角色模式", "单人模式"}:
            state.interaction_mode = "single"
            state.queued_events = []
            if state.selected_character:
                return f"已切换到单角色模式。当前角色：{state.selected_character}"
            return "已切换到单角色模式。发送「角色列表」选择角色。"
        if normalized in {"导演模式", "多角色模式"}:
            return await self._enter_director_mode(state)

        if normalized in {"加入对白", "加入动作", "加入环境"}:
            return f"用法：{normalized} <内容>"
        queued_event = parse_queue_event(normalized)
        if queued_event is not None:
            return self._queue_event(state, queued_event)
        if normalized in {"待发送", "查看待发送"}:
            return format_queued_events(state.queued_events)
        if normalized == "清空待发送":
            state.queued_events = []
            return "已清空待发送事件。"

        if state.interaction_mode == "director":
            return await self._handle_director_input(state, normalized)
        return await self._handle_single_input(state, normalized)

    def _queue_event(self, state: ConversationState, event: dict[str, Any]) -> str:
        if state.interaction_mode == "director":
            if not state.director_session_id:
                return "请先创建或恢复导演场景。"
        elif not state.session_id or not state.selected_character:
            return "请先发送「角色列表」并选择角色。"
        state.queued_events.append(event)
        return format_queued_events(state.queued_events)

    async def _ensure_capabilities(self, state: ConversationState) -> dict[str, Any]:
        if not state.capabilities:
            state.capabilities = await self._agent.get_capabilities()
        return state.capabilities

    async def _show_service_status(self, state: ConversationState) -> str:
        status = await self._agent.get_status()
        capabilities = await self._ensure_capabilities(state)
        service_status = str(status.get("status", "unknown"))
        version = str(status.get("version", "unknown"))
        dialogue_version = int(capabilities.get("dialogue_api_version", 1) or 1)
        director_enabled = int(capabilities.get("director_mode", 0) or 0) >= 1
        tts_enabled = int(capabilities.get("tts_jobs", 0) or 0) >= 1
        return (
            "Agent 服务状态：\n"
            f"- 状态：{service_status}\n"
            f"- 服务版本：{version}\n"
            f"- 对话 API：v{dialogue_version}\n"
            f"- 导演模式：{'可用' if director_enabled else '不可用'}\n"
            f"- TTS：{'可用' if tts_enabled else '未启用'}"
        )

    async def _handle_single_input(self, state: ConversationState, normalized: str) -> str:
        if not normalized:
            return await self._prompt_character_selection(state, force_refresh=False)
        if normalized in {"当前角色", "当前", "查看角色"}:
            if state.selected_character:
                return f"你当前使用的角色是：{state.selected_character}"
            return "你还没有选择角色，发送「角色列表」开始。"
        if normalized in {"查看记录", "查看历史", "历史记录", "history"}:
            return await self._show_history(state)
        if normalized in {"角色列表", "切换角色"}:
            return await self._prompt_character_selection(state, force_refresh=True)
        if normalized.startswith("切换角色 "):
            selection = normalized[len("切换角色 ") :].strip()
            if not selection:
                return await self._prompt_character_selection(state, force_refresh=True)
            state.awaiting_character_choice = True
            return await self._select_character(state, selection)
        if normalized == "清空记录":
            return "该操作会永久删除当前角色历史。请发送「清空记录 确认」。"
        if normalized == "清空记录 确认":
            return await self._clear_current_history(state)
        if normalized == "重新生成":
            return await self._regenerate_single_reply(state)
        if normalized.startswith("编辑上一句 "):
            edited_text = normalized[len("编辑上一句 ") :].strip()
            return await self._regenerate_single_reply(state, edited_text=edited_text)
        if normalized == "编辑上一句":
            return "用法：编辑上一句 <新的内容>"

        if state.awaiting_character_choice:
            return await self._select_character(state, normalized)
        if not state.session_id or not state.selected_character:
            return await self._prompt_character_selection(state, force_refresh=False)

        if normalized == "发送":
            return await self._send_single_events(state, final_text="")
        if normalized.startswith("发送 "):
            return await self._send_single_events(
                state,
                final_text=normalized[len("发送 ") :].strip(),
            )
        return await self._send_single_events(state, direct_event=parse_direct_event(normalized))

    async def _show_history(self, state: ConversationState) -> str:
        if not state.user_uuid:
            return "无法识别你的用户身份，请稍后再试。"
        if not state.selected_character:
            return "你还没有选择角色，发送「角色列表」开始。"

        messages = self._store.get_single_history(
            state.user_uuid,
            state.selected_character,
        )
        if not messages:
            messages = await self._agent.get_history(
                user_uuid=state.user_uuid,
                character_name=state.selected_character,
                limit=0,
            )
            if messages:
                self._store.replace_single_history(
                    state.user_uuid,
                    state.selected_character,
                    messages,
                )
        if not messages:
            return f"你和「{state.selected_character}」还没有历史记录。"

        visible_messages = messages[-10:]
        lines = [f"你和「{state.selected_character}」最近 {len(visible_messages)} 条记录："]
        for index, message in enumerate(visible_messages, start=1):
            role = str(message.get("role", "")).strip().lower()
            if role == "assistant":
                role_label = state.selected_character
                action = str(message.get("action", "")).strip()
                dialogue = str(message.get("dialogue") or message.get("content") or "").strip()
                content = f"{action} {dialogue}".strip() if action and action != "无" else dialogue
            else:
                role_label = "环境" if input_mode_from_history(message) == "scene_event" else "你"
                content = str(message.get("content", "")).strip()
            content = content.replace("\n", " ")
            if len(content) > 70:
                content = f"{content[:70]}..."
            lines.append(f"{index}. {role_label}：{content}")
        return "\n".join(lines)

    async def _prompt_character_selection(self, state: ConversationState, force_refresh: bool) -> str:
        characters = await self._agent.list_characters(force_refresh=force_refresh)
        if not characters:
            return "当前没有可用角色，请稍后再试。"

        state.character_options = characters
        state.awaiting_character_choice = True
        current = state.selected_character or "未选择"
        return (
            f"当前角色：{current}\n"
            "请选择角色（发送编号或角色名）：\n"
            f"{format_character_choices(characters)}"
        )

    async def _select_character(self, state: ConversationState, selection: str) -> str:
        if not state.character_options:
            state.character_options = await self._agent.list_characters(force_refresh=False)

        chosen = resolve_character_selection(selection, state.character_options)
        if not chosen:
            return (
                "未匹配到角色，请发送正确的编号或角色名。\n"
                f"{format_character_choices(state.character_options)}"
            )

        load_result = await self._agent.load_character(chosen, user_uuid=state.user_uuid)
        state.selected_character = chosen
        state.session_id = load_result.session_id
        if load_result.user_uuid:
            state.user_uuid = load_result.user_uuid
        state.awaiting_character_choice = False
        state.queued_events = []
        restored_messages = await self._synchronize_single_history(
            state,
            backend_restored_messages=load_result.restored_history_messages,
        )
        return (
            f"已切换角色为「{chosen}」。\n"
            f"已恢复历史：{restored_messages} 条。\n"
            "可直接聊天，也可使用「动作」「环境」等剧情输入。"
        )

    async def _send_single_events(
        self,
        state: ConversationState,
        final_text: str = "",
        direct_event: dict[str, Any] | None = None,
    ) -> str:
        outgoing = list(state.queued_events)
        if direct_event is not None:
            outgoing.append(direct_event)
        elif final_text:
            outgoing.append(build_dialogue_event(final_text, "dialogue"))
        if not outgoing:
            return "没有可发送的内容。可直接输入文字，或先使用「加入动作/环境」。"

        final_event = outgoing[-1]
        reply = await self._chat_with_agent(
            state,
            final_event=final_event,
            context_events=outgoing[:-1],
        )
        state.queued_events = []
        return reply

    async def _chat_with_agent(
        self,
        state: ConversationState,
        final_event: dict[str, Any],
        context_events: list[dict[str, Any]],
    ) -> str:
        assert state.session_id is not None
        assert state.selected_character is not None
        message = str(final_event.get("content", "")).strip()
        event_fields = dialogue_event_fields(final_event, context_events)

        try:
            reply = await self._agent.chat(
                state.session_id,
                message,
                text_only=False,
                generate_voice=False,
                dialogue_event=event_fields,
            )
        except AgentSessionExpiredError:
            LOGGER.info("Agent session expired, reload character=%s", state.selected_character)
            await self._reload_single_session(state)
            reply = await self._agent.chat(
                state.session_id,
                message,
                text_only=False,
                generate_voice=False,
                dialogue_event=event_fields,
            )
        if state.user_uuid:
            self._store.append_single_messages(
                state.user_uuid,
                state.selected_character,
                [
                    *[
                        self._single_user_history_record(event)
                        for event in context_events
                    ],
                    self._single_user_history_record(final_event),
                    {
                        "role": "assistant",
                        "content": reply,
                        "source_format": "qq_bot_local",
                    },
                ],
            )
        return f"{state.selected_character}：\n{reply}"

    async def _reload_single_session(self, state: ConversationState) -> int:
        load_result = await self._load_single_session(state)
        return await self._synchronize_single_history(
            state,
            backend_restored_messages=load_result.restored_history_messages,
        )

    async def _load_single_session(
        self,
        state: ConversationState,
    ) -> LoadCharacterResult:
        assert state.selected_character is not None
        load_result = await self._agent.load_character(
            state.selected_character,
            user_uuid=state.user_uuid,
        )
        state.session_id = load_result.session_id
        if load_result.user_uuid:
            state.user_uuid = load_result.user_uuid
        return load_result

    async def _synchronize_single_history(
        self,
        state: ConversationState,
        backend_restored_messages: int = 0,
    ) -> int:
        if not state.user_uuid or not state.selected_character or not state.session_id:
            return 0
        local_messages = self._store.get_single_history(
            state.user_uuid,
            state.selected_character,
        )
        history_read_failed = False
        try:
            backend_messages = await self._agent.get_history(
                state.user_uuid,
                state.selected_character,
                limit=0,
            )
        except AgentError as exc:
            LOGGER.warning(
                "Could not read Agent history during synchronization, use local copy: %s",
                exc,
            )
            backend_messages = []
            history_read_failed = True

        if backend_messages:
            if len(backend_messages) >= len(local_messages):
                self._store.replace_single_history(
                    state.user_uuid,
                    state.selected_character,
                    backend_messages,
                )
                return len(backend_messages)
            # A shorter remote copy means the Space retained only part of the
            # conversation. Clear it before importing to avoid duplicate JSONL
            # records across old and newly imported Agent sessions.
            await self._agent.clear_history(
                state.user_uuid,
                state.selected_character,
            )
            await self._agent.import_history(
                state.session_id,
                local_messages,
                replace_current=True,
                source="qq_bot_local_restore",
            )
            return len(local_messages)
        if local_messages:
            if history_read_failed and backend_restored_messages > 0:
                return max(len(local_messages), backend_restored_messages)
            await self._agent.import_history(
                state.session_id,
                local_messages,
                replace_current=True,
                source="qq_bot_local_restore",
            )
            return len(local_messages)
        return max(len(backend_messages), int(backend_restored_messages or 0))

    @staticmethod
    def _single_user_history_record(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "role": "user",
            "content": str(event.get("content", "")).strip(),
            "speaker": event.get("speaker"),
            "event_type": event.get("event_type") or "dialogue",
            "event_schema_version": 1,
        }

    async def _clear_current_history(self, state: ConversationState) -> str:
        if not state.user_uuid or not state.selected_character:
            return "请先选择角色。"
        result = await self._agent.clear_history(state.user_uuid, state.selected_character)
        locally_deleted = self._store.clear_single_history(
            state.user_uuid,
            state.selected_character,
        )
        state.queued_events = []
        deleted_messages = int(result.get("deleted_messages", 0) or 0)
        deleted_messages = max(deleted_messages, locally_deleted)
        return f"已清空你和「{state.selected_character}」的历史记录（{deleted_messages} 条）。"

    async def _regenerate_single_reply(
        self,
        state: ConversationState,
        edited_text: str = "",
    ) -> str:
        if not state.user_uuid or not state.selected_character or not state.session_id:
            return "请先选择角色并完成至少一轮对话。"
        messages = self._store.get_single_history(
            state.user_uuid,
            state.selected_character,
        )
        if not messages:
            messages = await self._agent.get_history(
                state.user_uuid,
                state.selected_character,
                limit=0,
            )
            if messages:
                self._store.replace_single_history(
                    state.user_uuid,
                    state.selected_character,
                    messages,
                )
        user_index = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if str(messages[index].get("role", "")).lower() == "user"
            ),
            -1,
        )
        if user_index < 0:
            return "没有可重新生成的训练员发言。"

        original = messages[user_index]
        content = (edited_text or str(original.get("content", ""))).strip()
        if not content:
            return "编辑后的内容不能为空。"
        prefix_messages = messages[:user_index]
        await self._agent.clear_history(
            state.user_uuid,
            state.selected_character,
        )
        try:
            await self._agent.import_history(
                state.session_id,
                prefix_messages,
                replace_current=True,
                source="qq_bot_regenerate_last_user",
            )
        except AgentHttpError as exc:
            if exc.status != 404:
                state.session_id = None
                raise
            await self._load_single_session(state)
            assert state.session_id is not None
            try:
                await self._agent.import_history(
                    state.session_id,
                    prefix_messages,
                    replace_current=True,
                    source="qq_bot_regenerate_last_user",
                )
            except AgentError:
                state.session_id = None
                raise
        except AgentError:
            state.session_id = None
            raise
        self._store.replace_single_history(
            state.user_uuid,
            state.selected_character,
            prefix_messages,
        )
        state.queued_events = []
        event = build_dialogue_event(content, input_mode_from_history(original))
        reply = await self._chat_with_agent(state, event, [])
        prefix = "已按新内容重新生成。" if edited_text else "已重新生成上一轮回复。"
        return f"{prefix}\n{reply}"

    async def _enter_director_mode(self, state: ConversationState) -> str:
        capabilities = await self._ensure_capabilities(state)
        if int(capabilities.get("director_mode", 0) or 0) < 1:
            return "当前 Agent 后端不支持导演模式。"
        state.interaction_mode = "director"
        state.awaiting_character_choice = False
        state.queued_events = []
        if not state.director_templates:
            state.director_templates = await self._agent.list_director_templates()
        if state.director_session_id and state.director_snapshot:
            return f"已切换到导演模式。\n{self._format_director_snapshot(state.director_snapshot)}"
        return f"已切换到导演模式。\n{self._format_director_templates(state.director_templates)}"

    async def _handle_director_input(self, state: ConversationState, normalized: str) -> str:
        if normalized in {"场景列表", "导演场景列表"}:
            if not state.director_templates:
                state.director_templates = await self._agent.list_director_templates()
            return self._format_director_templates(state.director_templates)
        if normalized.startswith("创建场景 "):
            return await self._create_preset_scene(
                state,
                normalized[len("创建场景 ") :].strip(),
            )
        if normalized == "创建场景":
            return "用法：创建场景 <编号或名称> | <角色1,角色2> | <可选剧情大纲>"
        if normalized.startswith("创建自定义场景 "):
            return await self._create_custom_scene(
                state,
                normalized[len("创建自定义场景 ") :].strip(),
            )
        if normalized == "创建自定义场景":
            return "用法：创建自定义场景 <地点> | <角色1,角色2> | <可选场景名> | <可选剧情大纲>"
        if normalized in {"导演状态", "当前场景"}:
            if not state.director_snapshot:
                return "当前没有活动场景。发送「场景列表」开始。"
            return self._format_director_snapshot(state.director_snapshot)
        if normalized in {"场景历史", "导演历史"}:
            return await self._show_director_history(state)
        if normalized.startswith("恢复场景 "):
            return await self._resume_director_scene(
                state,
                normalized[len("恢复场景 ") :].strip(),
            )
        if normalized == "恢复场景":
            return "请先发送「场景历史」，再使用「恢复场景 <编号>」。"
        if normalized == "结束场景":
            return await self._end_director_scene(state)
        if normalized == "重新生成":
            return await self._regenerate_director_reply(state)
        if normalized.startswith("删除场景记录 "):
            return await self._delete_director_history_command(
                state,
                normalized[len("删除场景记录 ") :].strip(),
            )

        if not state.director_session_id:
            return f"当前没有活动场景。\n{DIRECTOR_GUIDE_TEXT}"
        if normalized == "发送":
            return await self._send_director_events(state, final_text="")
        if normalized.startswith("发送 "):
            return await self._send_director_events(
                state,
                final_text=normalized[len("发送 ") :].strip(),
            )
        if not normalized:
            return DIRECTOR_GUIDE_TEXT
        return await self._send_director_events(state, direct_event=parse_direct_event(normalized))

    def _format_director_templates(self, templates: list[dict[str, Any]]) -> str:
        if not templates:
            return "当前没有可用的导演场景预设。"
        lines = ["导演场景预设："]
        for index, template in enumerate(templates, start=1):
            name = str(template.get("name", template.get("template_id", "未命名")))
            description = str(template.get("description", "")).strip()
            lines.append(f"{index}. {name}" + (f"：{description}" if description else ""))
        lines.append("创建：创建场景 <编号> | <角色1,角色2> | <可选剧情大纲>")
        return "\n".join(lines)

    async def _resolve_cast(self, state: ConversationState, raw_names: str) -> list[str] | None:
        if not state.character_options:
            state.character_options = await self._agent.list_characters(force_refresh=False)
        parts = [item.strip() for item in raw_names.replace("，", ",").replace("、", ",").split(",")]
        parts = [item for item in parts if item]
        resolved: list[str] = []
        for part in parts:
            name = resolve_character_selection(part, state.character_options)
            if not name:
                return None
            if name not in resolved:
                resolved.append(name)
        max_participants = int(state.capabilities.get("director_max_participants", 3) or 3)
        if not resolved or len(resolved) > max_participants:
            return None
        return resolved

    def _resolve_template(
        self,
        selection: str,
        templates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if selection.isdigit():
            index = int(selection) - 1
            if 0 <= index < len(templates):
                return templates[index]
        normalized = selection.lower()
        exact = [
            item
            for item in templates
            if normalized
            in {
                str(item.get("template_id", "")).lower(),
                str(item.get("name", "")).lower(),
            }
        ]
        if exact:
            return exact[0]
        partial = [
            item
            for item in templates
            if normalized in str(item.get("name", "")).lower()
        ]
        return partial[0] if len(partial) == 1 else None

    async def _create_preset_scene(self, state: ConversationState, arguments: str) -> str:
        if state.director_session_id:
            return "当前已有活动场景。请先发送「结束场景」，再创建新场景。"
        parts = [item.strip() for item in arguments.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            return "用法：创建场景 <编号或名称> | <角色1,角色2> | <可选剧情大纲>"
        if not state.director_templates:
            state.director_templates = await self._agent.list_director_templates()
        template = self._resolve_template(parts[0], state.director_templates)
        cast = await self._resolve_cast(state, parts[1])
        if not template:
            return "未找到场景预设，请发送「场景列表」查看编号。"
        if not cast:
            return "角色名称未匹配，或选择数量超出后端限制。"
        story_outline = parts[2] if len(parts) >= 3 else ""
        snapshot = await self._agent.create_director_session(
            character_names=cast,
            user_uuid=state.user_uuid or "",
            template_id=str(template.get("template_id", "")),
            story_outline=story_outline,
        )
        self._apply_director_snapshot(state, snapshot)
        return f"导演场景已创建。\n{self._format_director_snapshot(snapshot)}"

    async def _create_custom_scene(self, state: ConversationState, arguments: str) -> str:
        if state.director_session_id:
            return "当前已有活动场景。请先发送「结束场景」，再创建新场景。"
        parts = [item.strip() for item in arguments.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            return "用法：创建自定义场景 <地点> | <角色1,角色2> | <可选场景名> | <可选剧情大纲>"
        cast = await self._resolve_cast(state, parts[1])
        if not cast:
            return "角色名称未匹配，或选择数量超出后端限制。"
        scene_name = parts[2] if len(parts) >= 3 and parts[2] else "自定义场景"
        story_outline = parts[3] if len(parts) >= 4 else ""
        custom_scene = {
            "name": scene_name,
            "initial_state": {"location": parts[0]},
            "opening_narration": "",
            "tags": ["QQ Bot 自定义"],
        }
        snapshot = await self._agent.create_director_session(
            character_names=cast,
            user_uuid=state.user_uuid or "",
            custom_scene=custom_scene,
            story_outline=story_outline,
        )
        self._apply_director_snapshot(state, snapshot)
        return f"自定义导演场景已创建。\n{self._format_director_snapshot(snapshot)}"

    def _apply_director_snapshot(
        self,
        state: ConversationState,
        snapshot: dict[str, Any],
    ) -> None:
        state.director_snapshot = snapshot
        state.director_session_id = str(snapshot.get("session_id", "")).strip() or None
        state.last_director_event_id = self._latest_character_reply_id(snapshot.get("events"))
        state.queued_events = []
        if state.user_uuid and state.director_session_id:
            self._store.save_director_snapshot(state.user_uuid, snapshot)

    @staticmethod
    def _latest_character_reply_id(events: Any) -> str | None:
        if not isinstance(events, list):
            return None
        for event in reversed(events):
            if isinstance(event, dict) and event.get("event_type") == "character_reply":
                event_id = str(event.get("event_id", "")).strip()
                if event_id:
                    return event_id
        return None

    def _format_director_snapshot(self, snapshot: dict[str, Any]) -> str:
        template = snapshot.get("template") if isinstance(snapshot.get("template"), dict) else {}
        state_data = snapshot.get("scene_state") if isinstance(snapshot.get("scene_state"), dict) else {}
        participants = snapshot.get("participants") if isinstance(snapshot.get("participants"), list) else []
        names = []
        for item in participants:
            actor = item.get("actor") if isinstance(item, dict) else None
            if isinstance(actor, dict) and actor.get("actor_type") in {"umamusume", "npc"}:
                names.append(str(actor.get("display_name", "")))
        location_parts = [
            str(state_data.get(key, "")).strip()
            for key in ("location", "sub_location", "time", "weather")
            if str(state_data.get(key, "")).strip()
        ]
        lines = [
            f"场景：{template.get('name', '导演场景')}",
            f"角色：{'、'.join(names) or '未识别'}",
            f"地点：{' / '.join(location_parts) or '未设置'}",
            f"轮次：{int(snapshot.get('turn_index', 0) or 0)}",
        ]
        outline = str(snapshot.get("story_outline", "")).strip()
        if outline:
            lines.append(f"大纲：{outline}")
        recent = self._format_director_events(snapshot.get("events", []), limit=3)
        if recent:
            lines.append(recent)
        return "\n".join(lines)

    def _format_director_events(self, events: Any, limit: int = 8) -> str:
        if not isinstance(events, list):
            return ""
        blocks: list[str] = []
        for event in events:
            if not isinstance(event, dict) or event.get("hidden"):
                continue
            event_type = str(event.get("event_type", ""))
            actor = event.get("actor") if isinstance(event.get("actor"), dict) else {}
            if actor.get("actor_type") == "trainer" and event_type in {"dialogue", "action"}:
                continue
            if event_type == "character_reply":
                name = str(actor.get("display_name", "角色"))
                action = str(event.get("action", "")).strip()
                dialogue = str(event.get("dialogue") or event.get("content") or "").strip()
                lines = [f"【{name}】"]
                if action and action != "无":
                    lines.append(f"动作：{action}")
                if dialogue:
                    lines.append(f"对白：{dialogue}")
                blocks.append("\n".join(lines))
            elif event_type in {"narration", "scene_event", "scene_change"}:
                content = str(event.get("content") or event.get("dialogue") or "").strip()
                if content:
                    blocks.append(f"【环境】{content}")
        return "\n".join(blocks[-limit:])

    async def _send_director_events(
        self,
        state: ConversationState,
        final_text: str = "",
        direct_event: dict[str, Any] | None = None,
    ) -> str:
        if not state.director_session_id or not state.user_uuid:
            return "请先创建或恢复导演场景。"
        outgoing = list(state.queued_events)
        if direct_event is not None:
            outgoing.append(direct_event)
        elif final_text:
            outgoing.append(build_dialogue_event(final_text, "dialogue"))
        if not outgoing:
            return "没有可发送的内容。"
        request_events = [event_for_request(event) for event in outgoing]

        try:
            result = await self._agent.director_turn(
                state.director_session_id,
                state.user_uuid,
                request_events,
            )
        except AgentHttpError as exc:
            if exc.status != 404:
                raise
            await self._restore_director_session(state)
            assert state.director_session_id is not None
            result = await self._agent.director_turn(
                state.director_session_id,
                state.user_uuid,
                request_events,
            )

        state.queued_events = []
        self._update_director_snapshot(state, result)
        rendered = self._format_director_events(result.get("events", []))
        scene_state = result.get("scene_state") if isinstance(result.get("scene_state"), dict) else {}
        location = str(scene_state.get("location", "")).strip()
        if location:
            rendered = f"{rendered}\n【场景】{location}" if rendered else f"【场景】{location}"
        return rendered or "本轮场景已更新。"

    def _update_director_snapshot(
        self,
        state: ConversationState,
        result: dict[str, Any],
    ) -> None:
        if state.director_snapshot is None:
            return
        current_events = state.director_snapshot.setdefault("events", [])
        known_ids = {
            item.get("event_id")
            for item in current_events
            if isinstance(item, dict)
        }
        new_events = result.get("events") if isinstance(result.get("events"), list) else []
        for event in new_events:
            if isinstance(event, dict) and event.get("event_id") not in known_ids:
                current_events.append(event)
        if isinstance(result.get("scene_state"), dict):
            state.director_snapshot["scene_state"] = result["scene_state"]
        state.director_snapshot["turn_index"] = int(result.get("turn_index", 0) or 0)
        state.director_snapshot["last_active_at"] = datetime.now().isoformat()
        state.last_director_event_id = self._latest_character_reply_id(current_events)
        if state.user_uuid and state.director_session_id:
            self._store.save_director_snapshot(
                state.user_uuid,
                state.director_snapshot,
            )

    async def _restore_director_session(self, state: ConversationState) -> None:
        assert state.director_session_id is not None
        assert state.user_uuid is not None
        try:
            snapshot = await self._agent.resume_director_history(
                state.director_session_id,
                state.user_uuid,
            )
        except AgentHttpError as history_error:
            if history_error.status != 404 or not state.director_snapshot:
                raise
            snapshot = await self._agent.recover_director_session(
                state.director_snapshot,
                state.user_uuid,
            )
        self._apply_director_snapshot(state, snapshot)

    async def _show_director_history(self, state: ConversationState) -> str:
        if not state.user_uuid:
            return "无法识别用户身份。"
        try:
            remote_scenes = await self._agent.get_director_history(
                state.user_uuid,
                limit=20,
            )
        except AgentError as exc:
            LOGGER.warning("Could not read Agent director history, use local copy: %s", exc)
            remote_scenes = []
        local_scenes = [
            self._director_snapshot_summary(snapshot)
            for snapshot in self._store.list_director_snapshots(
                state.user_uuid,
                limit=20,
            )
        ]
        # Local snapshots are the durable source for this Bot and must remain
        # visible even when the remote list already contains 20 older scenes.
        scenes = list(local_scenes)
        known_session_ids = {
            str(scene.get("session_id", ""))
            for scene in scenes
            if isinstance(scene, dict)
        }
        scenes.extend(
            scene
            for scene in remote_scenes
            if str(scene.get("session_id", "")) not in known_session_ids
        )
        state.director_history_options = scenes
        if not scenes:
            return "还没有可恢复的导演场景。"
        lines = ["导演场景历史："]
        for index, scene in enumerate(scenes[:10], start=1):
            names = "、".join(str(item) for item in scene.get("character_names", []))
            preview = str(scene.get("preview", "")).strip()
            lines.append(
                f"{index}. {scene.get('scene_name', '导演场景')} · {names or '未知角色'} · "
                f"第{int(scene.get('turn_index', 0) or 0)}轮"
            )
            if preview:
                lines.append(f"   {preview[:80]}")
        lines.append("继续：恢复场景 <编号>")
        return "\n".join(lines)

    @staticmethod
    def _director_snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
        template = (
            snapshot.get("template")
            if isinstance(snapshot.get("template"), dict)
            else {}
        )
        participants = (
            snapshot.get("participants")
            if isinstance(snapshot.get("participants"), list)
            else []
        )
        character_names: list[str] = []
        for participant in participants:
            actor = participant.get("actor") if isinstance(participant, dict) else None
            if not isinstance(actor, dict):
                continue
            if actor.get("actor_type") in {"umamusume", "npc"}:
                name = str(actor.get("display_name", "")).strip()
                if name:
                    character_names.append(name)
        preview = ""
        events = snapshot.get("events")
        if isinstance(events, list):
            for event in reversed(events):
                if not isinstance(event, dict) or event.get("hidden"):
                    continue
                preview = str(
                    event.get("dialogue")
                    or event.get("content")
                    or event.get("action")
                    or ""
                ).strip()
                if preview:
                    break
        scene_state = (
            snapshot.get("scene_state")
            if isinstance(snapshot.get("scene_state"), dict)
            else {}
        )
        return {
            "session_id": str(snapshot.get("session_id", "")),
            "scene_name": str(template.get("name", "导演场景")),
            "character_names": character_names,
            "location": str(scene_state.get("location", "")),
            "turn_index": int(snapshot.get("turn_index", 0) or 0),
            "preview": preview[:160],
            "updated_at": str(snapshot.get("last_active_at", "")),
            "local_snapshot": True,
        }

    def _resolve_history_scene(
        self,
        selection: str,
        scenes: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if selection.isdigit():
            index = int(selection) - 1
            if 0 <= index < len(scenes):
                return scenes[index]
        exact = [item for item in scenes if str(item.get("session_id", "")) == selection]
        if exact:
            return exact[0]
        partial = [
            item
            for item in scenes
            if selection.lower() in str(item.get("scene_name", "")).lower()
        ]
        return partial[0] if len(partial) == 1 else None

    async def _resume_director_scene(self, state: ConversationState, selection: str) -> str:
        if not state.user_uuid:
            return "无法识别用户身份。"
        if state.director_session_id:
            return "当前已有活动场景。请先发送「结束场景」，再恢复其他场景。"
        if not state.director_history_options:
            state.director_history_options = await self._agent.get_director_history(
                state.user_uuid,
                limit=20,
            )
        scene = self._resolve_history_scene(selection, state.director_history_options)
        if not scene:
            return "未找到场景，请先发送「场景历史」查看编号。"
        session_id = str(scene.get("session_id", ""))
        try:
            snapshot = await self._agent.resume_director_history(
                session_id,
                state.user_uuid,
            )
        except AgentHttpError as exc:
            if exc.status != 404:
                raise
            local_snapshot = self._store.get_director_snapshot(
                state.user_uuid,
                session_id,
            )
            if not local_snapshot:
                raise
            snapshot = await self._agent.recover_director_session(
                local_snapshot,
                state.user_uuid,
            )
        self._apply_director_snapshot(state, snapshot)
        return f"已恢复导演场景。\n{self._format_director_snapshot(snapshot)}"

    async def _end_director_scene(self, state: ConversationState) -> str:
        if not state.director_session_id or not state.user_uuid:
            return "当前没有活动场景。"
        try:
            await self._agent.delete_director_session(
                state.director_session_id,
                state.user_uuid,
            )
        except AgentHttpError as exc:
            if exc.status != 404:
                raise
        state.director_session_id = None
        state.director_snapshot = None
        state.last_director_event_id = None
        state.queued_events = []
        return "已结束当前导演场景。场景历史仍保留，可用「场景历史」继续。"

    async def _regenerate_director_reply(self, state: ConversationState) -> str:
        if not state.director_session_id or not state.user_uuid:
            return "当前没有活动场景。"
        event_id = state.last_director_event_id or self._latest_character_reply_id(
            (state.director_snapshot or {}).get("events")
        )
        if not event_id:
            return "当前场景还没有可重新生成的角色回复。"
        try:
            result = await self._agent.regenerate_director_reply(
                state.director_session_id,
                event_id,
                state.user_uuid,
            )
        except AgentHttpError as exc:
            if exc.status != 404:
                raise
            await self._restore_director_session(state)
            assert state.director_session_id is not None
            result = await self._agent.regenerate_director_reply(
                state.director_session_id,
                event_id,
                state.user_uuid,
            )
        event = result.get("event") if isinstance(result.get("event"), dict) else None
        if not event:
            raise AgentError("Invalid director regenerate response")
        if state.director_snapshot:
            events = state.director_snapshot.get("events", [])
            for index, current in enumerate(events):
                if isinstance(current, dict) and current.get("event_id") == event_id:
                    events[index] = event
                    break
            if isinstance(result.get("scene_state"), dict):
                state.director_snapshot["scene_state"] = result["scene_state"]
            state.director_snapshot["last_active_at"] = datetime.now().isoformat()
        state.last_director_event_id = str(event.get("event_id", event_id))
        if state.director_snapshot:
            self._store.save_director_snapshot(
                state.user_uuid,
                state.director_snapshot,
            )
        return f"已重新生成角色回复。\n{self._format_director_events([event])}"

    async def _delete_director_history_command(
        self,
        state: ConversationState,
        arguments: str,
    ) -> str:
        if not arguments.endswith(" 确认"):
            return "该操作会永久删除场景历史。用法：删除场景记录 <编号> 确认"
        selection = arguments[: -len(" 确认")].strip()
        if not state.user_uuid:
            return "无法识别用户身份。"
        if not state.director_history_options:
            state.director_history_options = await self._agent.get_director_history(
                state.user_uuid,
                limit=20,
            )
        scene = self._resolve_history_scene(selection, state.director_history_options)
        if not scene:
            return "未找到场景，请先发送「场景历史」查看编号。"
        session_id = str(scene.get("session_id", ""))
        try:
            await self._agent.delete_director_history(session_id, state.user_uuid)
        except AgentHttpError as exc:
            if exc.status != 404:
                raise
        self._store.delete_director_snapshot(state.user_uuid, session_id)
        state.director_history_options = [
            item
            for item in state.director_history_options
            if str(item.get("session_id", "")) != session_id
        ]
        if state.director_session_id == session_id:
            state.director_session_id = None
            state.director_snapshot = None
            state.last_director_event_id = None
        return f"已删除场景历史「{scene.get('scene_name', '导演场景')}」。"
