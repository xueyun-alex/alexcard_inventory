import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from cozepy import COZE_CN_BASE_URL, ChatStatus, Coze, Message, TokenAuth

import config
from ollama_sdk import ChatTurn

logger = logging.getLogger(__name__)

_coze: Optional[Coze] = None
_bot_id: str = ""
_default_user_id: str = "python_user_002"

NO_VALID_ANSWER_MARKER = "未找到智能体的有效回答。"


@dataclass
class CozeTiming:
    create_s: float = 0.0
    poll_s: float = 0.0
    poll_count: int = 0
    list_s: float = 0.0
    total_s: float = 0.0


@dataclass
class CozeStatus:
    ok: bool
    detail: str


def _format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    return f"{seconds:.1f}s"


def init_coze(
    api_token: Optional[str] = None,
    bot_id: Optional[str] = None,
    default_user_id: str = "python_user_002",
) -> None:
    global _coze, _bot_id, _default_user_id
    token = (api_token or config.COZE_API_TOKEN).strip()
    bot = (bot_id or config.COZE_BOT_ID).strip()
    if not token:
        raise ValueError("Coze API Token 不能为空")
    if not bot:
        raise ValueError("Bot ID 不能为空")
    _coze = Coze(auth=TokenAuth(token=token), base_url=COZE_CN_BASE_URL)
    _bot_id = bot
    _default_user_id = default_user_id.strip() or "python_user_002"


def check_coze_ready(
    api_token: Optional[str] = None,
    bot_id: Optional[str] = None,
) -> CozeStatus:
    token = (api_token if api_token is not None else config.COZE_API_TOKEN).strip()
    bot = (bot_id if bot_id is not None else config.COZE_BOT_ID).strip()
    if not token:
        return CozeStatus(False, "未配置 COZE_API_TOKEN，请填写 Coze API Token")
    if not bot:
        return CozeStatus(False, "未配置 COZE_BOT_ID，请填写智能体 Bot ID")
    try:
        client = Coze(auth=TokenAuth(token=token), base_url=COZE_CN_BASE_URL)
        bot_info = client.bots.retrieve(bot_id=bot)
        name = getattr(bot_info, "name", "") or bot
        return CozeStatus(True, f"Coze 连接正常，智能体: {name}")
    except Exception as exc:
        return CozeStatus(False, f"Coze 连接失败: {exc}")


def _build_additional_messages(turns: list[ChatTurn]) -> list[Message]:
    if not turns:
        raise ValueError("对话历史不能为空")
    if turns[-1].role != "user":
        raise ValueError("最后一条消息必须是用户消息")

    messages: list[Message] = []
    for turn in turns:
        content = (turn.content or "").strip()
        if not content:
            continue
        if turn.role == "user":
            messages.append(Message.build_user_question_text(content))
        else:
            messages.append(Message.build_assistant_answer(content))
    return messages


def _run_chat(
    additional_messages: list[Message],
    user_id: str,
    verbose: bool,
) -> tuple[Optional[str], CozeTiming]:
    if _coze is None:
        raise RuntimeError("请先调用 init_coze() 初始化 Coze 客户端")

    timing = CozeTiming()

    create_start = time.perf_counter()
    chat_info = _coze.chat.create(
        bot_id=_bot_id,
        user_id=user_id,
        additional_messages=additional_messages,
    )
    timing.create_s = time.perf_counter() - create_start

    conversation_id = chat_info.conversation_id
    chat_id = chat_info.id

    if verbose:
        print("正在等待智能体思考并生成回答......")

    poll_start = time.perf_counter()
    while True:
        timing.poll_count += 1
        status_info = _coze.chat.retrieve(conversation_id=conversation_id, chat_id=chat_id)
        if status_info.status == ChatStatus.COMPLETED:
            break
        if status_info.status in [ChatStatus.FAILED, ChatStatus.REQUIRES_ACTION]:
            if verbose:
                print(f"执行失败或需要其他操作，状态为: {status_info.status}")
            return None, timing
        time.sleep(1)
    timing.poll_s = time.perf_counter() - poll_start

    list_start = time.perf_counter()
    messages = _coze.chat.messages.list(conversation_id=conversation_id, chat_id=chat_id)
    timing.list_s = time.perf_counter() - list_start

    for msg in messages:
        if msg.role == "assistant" and msg.type == "answer":
            content = (msg.content or "").strip()
            if content:
                return content, timing

    return None, timing


def _single_chat_attempt(query_text: str, user_id: str, verbose: bool) -> tuple[Optional[str], CozeTiming]:
    return _run_chat([Message.build_user_question_text(query_text)], user_id, verbose)


def chat_with_history(
    turns: list[ChatTurn],
    session_id: str = "",
    user_id: Optional[str] = None,
    max_retries: int = 2,
) -> Optional[str]:
    if _coze is None:
        raise RuntimeError("请先调用 init_coze() 初始化 Coze 客户端")

    uid = (user_id or "").strip() or _default_user_id
    additional_messages = _build_additional_messages(turns)
    retries = max(1, max_retries)

    for attempt in range(1, retries + 1):
        attempt_start = time.perf_counter()
        try:
            answer, timing = _run_chat(additional_messages, uid, verbose=False)
        except Exception as exc:
            logger.warning(
                "Coze 请求失败 [%s] 第 %d/%d 次: %s",
                session_id or "unknown",
                attempt,
                retries,
                exc,
            )
            answer, timing = None, CozeTiming()
        timing.total_s = time.perf_counter() - attempt_start

        if answer:
            logger.info(
                "Coze 回复完成 [%s]，耗时 %s（轮询 %d 次）",
                session_id or "unknown",
                _format_duration(timing.total_s),
                timing.poll_count,
            )
            return answer

        if attempt < retries:
            time.sleep(1)

    return None


def get_final_answer_sync(
    query_text: str,
    user_id: Optional[str] = None,
    verbose: bool = False,
    on_timing: Optional[Callable[[CozeTiming], None]] = None,
    max_retries: int = 3,
) -> Optional[str]:
    if _coze is None:
        raise RuntimeError("请先调用 init_coze() 初始化 Coze 客户端")

    uid = (user_id or "").strip() or _default_user_id
    retries = max(1, max_retries)

    for attempt in range(1, retries + 1):
        attempt_start = time.perf_counter()
        answer, attempt_timing = _single_chat_attempt(query_text, uid, verbose)
        attempt_timing.total_s = time.perf_counter() - attempt_start
        if on_timing is not None:
            on_timing(attempt_timing)

        if answer:
            return answer

        if attempt < retries:
            if verbose:
                print(
                    f"第 {attempt}/{retries} 次未找到有效回答，"
                    f"1 秒后重新询问…"
                )
            time.sleep(1)

    return None


if __name__ == "__main__":
    import sys

    if sys.platform == "win32" and sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")

    config.reload_config()
    status = check_coze_ready()
    print(f"Coze 状态: {status.detail}")
    if not status.ok:
        raise SystemExit(1)

    init_coze()
    sample = chat_with_history([ChatTurn(role="user", content="咨询烧烤")])
    print(f"\n样例回复:\n{sample}")
