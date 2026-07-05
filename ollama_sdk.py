"""Shared chat types used by Coze and other LLM SDK wrappers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChatTurn:
    role: str
    content: str
