from __future__ import annotations

import logging

import botpy
from botpy.message import GroupMessage

from .agent_client import AgentClient, AgentError, AgentSessionExpiredError
from .config import Settings
from .state_store import ConversationState, ConversationStore
from .text_utils import format_character_choices, normalize_group_text, resolve_character_selection, truncate_reply

LOGGER = logging.getLogger(__name__)

HELP_TEXT = (
    "可用命令：\n"
    "1) 角色列表\n"
    "2) 切换角色\n"
    "3) 当前角色\n"
    "直接 @我 + 内容 即可聊天。"
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
            response = await self._handle_user_input(group_openid, member_openid, text)
        except AgentError as exc:
            LOGGER.warning("Agent request failed while handling message: %s", exc)
            response = "对话服务暂时不可用，请稍后重试。"
        except Exception:
            LOGGER.exception("Unexpected error while handling message group=%s member=%s", group_openid, member_openid)
            response = "处理消息时发生错误，请稍后重试。"

        await message.reply(content=truncate_reply(response))

    async def _handle_user_input(self, group_openid: str, member_openid: str, text: str) -> str:
        state = self._store.get(group_openid, member_openid)
        normalized = text.strip()

        if not normalized:
            return await self._prompt_character_selection(state, force_refresh=False)

        if normalized in {"帮助", "help", "/help"}:
            return HELP_TEXT
        if normalized in {"当前角色", "当前"}:
            if state.selected_character:
                return f"你当前使用的角色是：{state.selected_character}"
            return "你还没有选择角色，发送「角色列表」开始。"
        if normalized in {"角色列表", "切换角色"}:
            return await self._prompt_character_selection(state, force_refresh=True)
        if normalized.startswith("切换角色 "):
            selection = normalized[len("切换角色 ") :].strip()
            if not selection:
                return await self._prompt_character_selection(state, force_refresh=True)
            state.awaiting_character_choice = True
            return await self._select_character(state, selection)

        if state.awaiting_character_choice:
            return await self._select_character(state, normalized)

        if not state.session_id or not state.selected_character:
            return await self._prompt_character_selection(state, force_refresh=False)

        return await self._chat_with_agent(state, normalized)

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

        session_id = await self._agent.load_character(chosen)
        state.selected_character = chosen
        state.session_id = session_id
        state.awaiting_character_choice = False
        return f"已切换角色为「{chosen}」。现在可以直接 @我 开始聊天。"

    async def _chat_with_agent(self, state: ConversationState, user_text: str) -> str:
        assert state.session_id is not None
        assert state.selected_character is not None

        try:
            reply = await self._agent.chat(state.session_id, user_text, text_only=False)
        except AgentSessionExpiredError:
            LOGGER.info("Agent session expired, reload character=%s", state.selected_character)
            state.session_id = await self._agent.load_character(state.selected_character)
            reply = await self._agent.chat(state.session_id, user_text, text_only=False)
        except AgentError as exc:
            LOGGER.warning("Agent request failed: %s", exc)
            return "对话服务暂时不可用，请稍后再试。"

        return f"{state.selected_character}：\n{reply}"
