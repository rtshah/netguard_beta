"""OpenAI vision wrapper using structured outputs (Pydantic-parsed responses)."""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import List, Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def _data_url(image_path: str) -> str:
    data = Path(image_path).read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"


class VisionLLM:
    def __init__(self, api_key: str, model: str):
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def parse(
        self,
        system: str,
        user_text: str,
        image_paths: List[str],
        schema: Type[T],
        max_retries: int = 3,
    ) -> T:
        content: list[dict] = [{"type": "text", "text": user_text}]
        for p in image_paths:
            content.append(
                {"type": "image_url", "image_url": {"url": _data_url(p), "detail": "high"}}
            )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ]

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                completion = self._client.chat.completions.parse(
                    model=self._model,
                    messages=messages,
                    response_format=schema,
                    temperature=0,
                )
                parsed = completion.choices[0].message.parsed
                if parsed is None:
                    raise RuntimeError("Model returned no parsed content.")
                return parsed
            except Exception as e:  # noqa: BLE001 - retry on transient/API errors
                last_err = e
                if attempt < max_retries - 1:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"LLM call failed after {max_retries} attempts: {last_err}")


class TextLLM:
    """Text-only structured-output wrapper (Module 03 submittal extraction)."""

    def __init__(self, api_key: str, model: str):
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def parse(
        self,
        system: str,
        user_text: str,
        schema: Type[T],
        max_retries: int = 3,
    ) -> T:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]
        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                completion = self._client.chat.completions.parse(
                    model=self._model,
                    messages=messages,
                    response_format=schema,
                    temperature=0,
                )
                parsed = completion.choices[0].message.parsed
                if parsed is None:
                    raise RuntimeError("Model returned no parsed content.")
                return parsed
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt < max_retries - 1:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"LLM call failed after {max_retries} attempts: {last_err}")
