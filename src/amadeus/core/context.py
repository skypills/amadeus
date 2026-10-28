from __future__ import annotations

from ..memory.history import Message


def build_messages(
    system_prompt: str,
    history: list[Message],
    memory_block: str = "",
) -> list[dict[str, str]]:
    system_parts = [system_prompt.strip()]
    if memory_block.strip():
        system_parts.append(memory_block.strip())
    messages: list[dict[str, str]] = [
        {"role": "system", "content": "\n\n".join(part for part in system_parts if part)}
    ]
    messages.extend(
        message.as_llm() for message in history if message.role in ("user", "assistant")
    )
    return messages
