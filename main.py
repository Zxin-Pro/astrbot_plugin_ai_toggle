# -*- coding: utf-8 -*-
"""
astrbot_plugin_ai_toggle

在群聊中通过文本指令「开启AI / 关闭AI / AI状态」按群控制机器人的 AI 回复能力。

- 仅 AstrBot 管理员（插件配置 admin_ids 或 AstrBot 全局 admins_id）可操作
- 非管理员发送指令文本时静默忽略，不回复任何内容
- 开关状态使用 AstrBot 插件 KV 存储（PluginKVStoreMixin）按群持久化
- 通过 on_llm_request 钩子拦截 LLM 请求，关闭状态下调用 event.stop_event() 终止本次调用
"""

import re
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star

# 指令匹配：兼容大小写、容忍首尾及指令内部空格
_CMD_ENABLE = re.compile(r"^开\s*启\s*ai$", re.IGNORECASE)
_CMD_DISABLE = re.compile(r"^关\s*闭\s*ai$", re.IGNORECASE)
_CMD_STATUS = re.compile(r"^ai\s*状\s*态$", re.IGNORECASE)

KV_KEY_FMT = "group_{group_id}_ai_enabled"


class AITogglePlugin(Star):
    """按群开关 AI 回复的插件"""

    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        # 群开关状态的内存缓存，键为群 ID（str），值为 bool。
        # KV 存储是异步接口，这里采用惰性加载：首次读写某个群时再查存储。
        self._states: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_group_id(event: AstrMessageEvent) -> str:
        """提取群 ID，统一转成字符串；私聊（群 ID 为空）返回空串。

        优先使用 event.get_group_id()（内部即读取 message_obj.group_id），
        并对 int/str 类型做兼容处理。
        """
        try:
            group_id = event.get_group_id()
        except Exception:
            group_id = getattr(event.message_obj, "group_id", "")
        if group_id is None:
            return ""
        return str(group_id).strip()

    def _get_admin_ids(self) -> list[str]:
        """获取管理员 ID 列表。

        优先使用插件配置 admin_ids；为空时回退到 AstrBot 全局配置
        data/cmd_config.json 中的 admins_id 字段。
        """
        plugin_admins = self.config.get("admin_ids") or []
        if isinstance(plugin_admins, list) and plugin_admins:
            return [str(x).strip() for x in plugin_admins if str(x).strip()]
        try:
            global_admins = self.context.get_config().get("admins_id", []) or []
            return [str(x).strip() for x in global_admins if str(x).strip()]
        except Exception as e:
            logger.warning(f"[ai_toggle] 读取全局管理员配置失败: {e}")
            return []

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        sender_id = str(event.get_sender_id() or "").strip()
        if not sender_id:
            return False
        return sender_id in self._get_admin_ids()

    def _default_enabled(self) -> bool:
        return bool(self.config.get("default_enabled", True))

    async def _get_state(self, group_id: str) -> bool:
        """读取某个群的开关状态（带内存缓存与异常回退）。"""
        if group_id in self._states:
            return self._states[group_id]
        state = self._default_enabled()
        try:
            stored = await self.get_kv_data(KV_KEY_FMT.format(group_id=group_id), None)
            if isinstance(stored, bool):
                state = stored
        except Exception as e:
            logger.warning(
                f"[ai_toggle] 读取群 {group_id} 开关状态失败，回退默认值: {e}"
            )
        self._states[group_id] = state
        return state

    async def _set_state(self, group_id: str, enabled: bool) -> None:
        """写入某个群的开关状态并持久化。"""
        self._states[group_id] = enabled
        try:
            await self.put_kv_data(KV_KEY_FMT.format(group_id=group_id), enabled)
        except Exception as e:
            logger.error(f"[ai_toggle] 持久化群 {group_id} 开关状态失败: {e}")

    # ------------------------------------------------------------------
    # 全局消息监听：处理开关指令
    # ------------------------------------------------------------------

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_group_message(self, event: AstrMessageEvent):
        """监听所有消息，匹配管理员发送的开关指令文本。

        注意：不使用 @filter.command（斜杠指令），而是纯文本匹配，
        直接发送「开启AI」等文本即可触发。
        """
        # 私聊 / 群 ID 为空时不处理
        group_id = self._normalize_group_id(event)
        if not group_id:
            return

        text = (event.message_str or "").strip()
        if not text:
            return

        is_enable = bool(_CMD_ENABLE.match(text))
        is_disable = bool(_CMD_DISABLE.match(text))
        is_status = bool(_CMD_STATUS.match(text))
        if not (is_enable or is_disable or is_status):
            return

        # 权限校验：非管理员发送开关指令时静默忽略，不回复任何内容
        if not self._is_admin(event):
            logger.info(
                f"[ai_toggle] 群 {group_id} 非管理员 {event.get_sender_id()} "
                f"尝试发送指令「{text}」，已忽略"
            )
            return

        if is_status:
            state = await self._get_state(group_id)
            yield event.plain_result(
                f"本群 AI 回复当前状态：{'开启' if state else '关闭'}"
            )
            event.stop_event()
            return

        await self._set_state(group_id, is_enable)
        logger.info(
            f"[ai_toggle] 群 {group_id} AI 回复已{'开启' if is_enable else '关闭'}"
            f"（操作人: {event.get_sender_id()}）"
        )

        # 终止事件继续传播，避免「开启AI」这段文本再被当作普通消息送入 LLM
        event.stop_event()

        if self.config.get("reply_on_toggle", True):
            yield event.plain_result(
                "已开启本群 AI 回复喵~" if is_enable else "已关闭本群 AI 回复喵~"
            )

    # ------------------------------------------------------------------
    # LLM 请求拦截
    # ------------------------------------------------------------------

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """LLM 调用前拦截：群开关为关闭时终止本次请求。

        中断机制说明（已对照 AstrBot 源码确认，pipeline/context_utils.py 的
        call_event_hook 与 process_stage/agent_sub_stages/internal.py）：
        钩子内抛出的异常会被 call_event_hook 捕获并仅记录日志，**无法**中断管线；
        正确做法是调用 event.stop_event()，call_event_hook 检测到
        event.is_stopped() 为 True 后返回 True，LLM 子阶段直接 return，
        本次 LLM 调用被静默终止（不会向群里发送任何内容）。
        """
        group_id = self._normalize_group_id(event)
        if not group_id:
            return

        enabled = await self._get_state(group_id)
        if enabled:
            return  # 开启状态：正常放行

        logger.info(f"[ai_toggle] 群 {group_id} AI 回复已关闭，拦截本次 LLM 请求")
        event.stop_event()
