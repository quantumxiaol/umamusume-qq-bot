from __future__ import annotations

import logging

import botpy
from botpy.message import C2CMessage, GroupMessage

from .agent_client import AgentClient, AgentError, AgentSessionExpiredError
from .config import Settings
from .state_store import ConversationState, ConversationStore
from .text_utils import format_character_choices, normalize_group_text, resolve_character_selection, truncate_reply

LOGGER = logging.getLogger(__name__)

COMMAND_GUIDE_TEXT = (
    "可用命令：\n"
    "1) 角色列表：查看可用角色并进入选择\n"
    "2) 切换角色：重新选择角色\n"
    "3) 切换角色 <角色名/编号>：直接切换角色\n"
    "4) 当前角色 / 查看角色：查看当前角色\n"
    "5) 查看记录：查看当前角色最近对话记录\n"
    "6) 帮助：查看命令说明"
)

WELCOME_TEXT = (
    "你好，我是赛马娘角色对话机器人。\n"
    f"{COMMAND_GUIDE_TEXT}\n"
    "选好角色后，直接发送内容即可聊天。"
)

HELP_TEXT = (
    f"{COMMAND_GUIDE_TEXT}\n"
    "群聊中 @我 + 内容，或好友私聊直接发内容即可聊天。"
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

        try:
            response = await self._handle_user_input(user_identity=member_openid, text=text)
        except AgentError as exc:
            LOGGER.warning("Agent request failed while handling message: %s", exc)
            response = "对话服务暂时不可用，请稍后重试。"
        except Exception:
            LOGGER.exception("Unexpected error while handling message group=%s member=%s", group_openid, member_openid)
            response = "处理消息时发生错误，请稍后重试。"

        await message.reply(content=truncate_reply(response))

    async def on_c2c_message_create(self, message: C2CMessage):
        user_openid = getattr(message.author, "user_openid", "") or ""
        text = normalize_group_text(message.content or "")

        LOGGER.info("c2c_message user=%s msg_id=%s text=%r", user_openid, message.id, text)

        if not user_openid:
            await message.reply(content="无法识别当前会话身份，请稍后重试。")
            return

        try:
            response = await self._handle_user_input(user_identity=user_openid, text=text)
        except AgentError as exc:
            LOGGER.warning("Agent request failed while handling c2c message: %s", exc)
            response = "对话服务暂时不可用，请稍后重试。"
        except Exception:
            LOGGER.exception("Unexpected error while handling c2c message user=%s", user_openid)
            response = "处理消息时发生错误，请稍后重试。"

        await message.reply(content=truncate_reply(response))

    async def _handle_user_input(self, user_identity: str, text: str) -> str:
        state = self._store.get(user_identity=user_identity)
        normalized = text.strip()
        first_interaction = not state.has_seen_welcome
        if first_interaction:
            state.has_seen_welcome = True

        if not normalized:
            response = await self._prompt_character_selection(state, force_refresh=False)
        elif normalized in {"帮助", "help", "/help"}:
            response = HELP_TEXT
        elif normalized in {"当前角色", "当前", "查看角色"}:
            if state.selected_character:
                response = f"你当前使用的角色是：{state.selected_character}"
            else:
                response = "你还没有选择角色，发送「角色列表」开始。"
        elif normalized in {"查看记录", "查看历史", "历史记录", "history"}:
            response = await self._show_history(state)
        elif normalized in {"角色列表", "切换角色"}:
            response = await self._prompt_character_selection(state, force_refresh=True)
        elif normalized.startswith("切换角色 "):
            selection = normalized[len("切换角色 ") :].strip()
            if not selection:
                response = await self._prompt_character_selection(state, force_refresh=True)
            else:
                state.awaiting_character_choice = True
                response = await self._select_character(state, selection)
        elif state.awaiting_character_choice:
            response = await self._select_character(state, normalized)
        elif not state.session_id or not state.selected_character:
            response = await self._prompt_character_selection(state, force_refresh=False)
        else:
            response = await self._chat_with_agent(state, normalized)

        if first_interaction:
            return f"{WELCOME_TEXT}\n\n{response}"
        return response

    async def _show_history(self, state: ConversationState) -> str:
        if not state.user_uuid:
            return "无法识别你的用户身份，请稍后再试。"
        if not state.selected_character:
            return "你还没有选择角色，发送「角色列表」开始。"

        messages = await self._agent.get_history(
            user_uuid=state.user_uuid,
            character_name=state.selected_character,
            limit=20,
        )
        if not messages:
            return f"你和「{state.selected_character}」还没有历史记录。"

        visible_messages = messages[-10:]
        lines = [f"你和「{state.selected_character}」最近 {len(visible_messages)} 条记录："]
        for index, message in enumerate(visible_messages, start=1):
            role = str(message.get("role", "")).strip().lower()
            if role == "assistant":
                role_label = state.selected_character
            elif role == "user":
                role_label = "你"
            else:
                role_label = role or "未知"

            content = str(message.get("content", "")).strip().replace("\n", " ")
            if len(content) > 60:
                content = f"{content[:60]}..."
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
        return (
            f"已切换角色为「{chosen}」。\n"
            f"已恢复历史：{load_result.restored_history_messages} 条。\n"
            "现在可以直接发送消息开始聊天。"
        )

    async def _chat_with_agent(self, state: ConversationState, user_text: str) -> str:
        assert state.session_id is not None
        assert state.selected_character is not None

        try:
            reply = await self._agent.chat(state.session_id, user_text, text_only=False)
        except AgentSessionExpiredError:
            LOGGER.info("Agent session expired, reload character=%s", state.selected_character)
            load_result = await self._agent.load_character(state.selected_character, user_uuid=state.user_uuid)
            state.session_id = load_result.session_id
            if load_result.user_uuid:
                state.user_uuid = load_result.user_uuid
            reply = await self._agent.chat(state.session_id, user_text, text_only=False)
        except AgentError as exc:
            LOGGER.warning("Agent request failed: %s", exc)
            return "对话服务暂时不可用，请稍后再试。"

        return f"{state.selected_character}：\n{reply}"
