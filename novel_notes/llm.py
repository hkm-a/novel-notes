"""OpenAI 兼容接口的 LLM 客户端。

支持 OpenAI、DeepSeek、Ollama /v1、vLLM、LM Studio 等常见服务。
包含超时、指数退避重试、错误信息提取等健壮性处理。
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """LLM 调用失败。"""


class _RetryableLLMError(LLMError):
    """可重试的 LLM 错误（限流、5xx、超时等）。"""


@dataclass
class LLMConfig:
    base_url: str
    api_key: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.3
    max_tokens: int = 2000
    timeout: float = 120.0
    max_retries: int = 5


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config
        self.session = requests.Session()
        base = config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            self.endpoint = base
        else:
            self.endpoint = f"{base}/chat/completions"

        self.headers = {"Content-Type": "application/json"}
        if config.api_key:
            self.headers["Authorization"] = f"Bearer {config.api_key}"

    def close(self) -> None:
        self.session.close()

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
            "stream": False,
        }
        if self.config.max_tokens:
            payload["max_tokens"] = self.config.max_tokens

        last_exc: Optional[Exception] = None
        for attempt in range(self.config.max_retries + 1):
            try:
                resp = self.session.post(
                    self.endpoint,
                    headers=self.headers,
                    json=payload,
                    timeout=self.config.timeout,
                )

                if resp.status_code >= 200 and resp.status_code < 300:
                    return self._extract_content(resp)

                body = self._safe_body(resp)
                if resp.status_code in RETRYABLE_STATUS:
                    raise _RetryableLLMError(
                        f"HTTP {resp.status_code}（可重试）: {body}"
                    )
                # 其他 4xx/3xx 一般是参数或鉴权问题，重试没有意义。
                raise LLMError(f"HTTP {resp.status_code}: {body}")

            except _RetryableLLMError as exc:
                last_exc = exc
                if attempt >= self.config.max_retries:
                    break
                delay = min(2 ** attempt + random.random() * 0.5, 60.0)
                logger.warning(
                    "LLM 调用失败（第 %d/%d 次）：%s；%.1fs 后重试",
                    attempt + 1,
                    self.config.max_retries + 1,
                    exc,
                    delay,
                )
                time.sleep(delay)
            except LLMError:
                # 非可重试错误（鉴权、参数错误等）直接抛出。
                raise
            except requests.RequestException as exc:
                last_exc = exc
                if attempt >= self.config.max_retries:
                    break
                delay = min(2 ** attempt + random.random() * 0.5, 60.0)
                logger.warning(
                    "网络请求失败（第 %d/%d 次）：%s；%.1fs 后重试",
                    attempt + 1,
                    self.config.max_retries + 1,
                    exc,
                    delay,
                )
                time.sleep(delay)

        raise LLMError(f"LLM 调用失败: {last_exc}") from last_exc

    def _safe_body(self, resp: requests.Response) -> str:
        try:
            return resp.text[:500]
        except Exception:
            return "<无法读取响应体>"

    def _extract_content(self, resp: requests.Response) -> str:
        try:
            data = resp.json()
        except ValueError as exc:
            raise LLMError(f"响应不是合法 JSON: {resp.text[:200]}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"响应中没有 choices: {str(data)[:500]}")

        message = choices[0].get("message") or {}
        content = message.get("content")
        if not content:
            # 部分推理模型把可见内容放在 reasoning_content，这里做兜底。
            content = message.get("reasoning_content") or ""
        if not content:
            raise LLMError("模型返回了空内容")

        return content.strip()
