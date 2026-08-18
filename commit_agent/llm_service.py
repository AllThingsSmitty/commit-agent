import time
from typing import Type, TypeVar
import anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# Rough character-to-token ratio; conservative to stay well under the 200k limit.
_CHARS_PER_TOKEN = 4
_MAX_PROMPT_CHARS = 150_000 * _CHARS_PER_TOKEN  # ~150k tokens

_RETRY_STATUSES = {429, 500, 502, 503, 529}
_MAX_RETRIES = 4
_BASE_DELAY = 1.0


class LLMService:
    def __init__(self, model: str = "claude-opus-5", max_tokens: int = 4096):
        self.client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def complete_structured(self, prompt: str, response_model: Type[T]) -> T:
        if len(prompt) > _MAX_PROMPT_CHARS:
            raise ValueError(
                f"Prompt is {len(prompt):,} chars (~{len(prompt) // _CHARS_PER_TOKEN:,} tokens), "
                f"which exceeds the {_MAX_PROMPT_CHARS // _CHARS_PER_TOKEN:,}-token safety limit. "
                "Reduce the number of files or lower DIFF_TRUNCATE_CHARS."
            )

        schema = response_model.model_json_schema()

        for attempt in range(_MAX_RETRIES):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    tools=[
                        {
                            "name": "respond",
                            "description": "Return your structured response",
                            "input_schema": schema,
                        }
                    ],
                    tool_choice={"type": "tool", "name": "respond"},
                    messages=[{"role": "user", "content": prompt}],
                )
            except anthropic.RateLimitError as exc:
                if attempt == _MAX_RETRIES - 1:
                    raise
                delay = _BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                continue
            except anthropic.APIStatusError as exc:
                if exc.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY * (2 ** attempt)
                    time.sleep(delay)
                    continue
                raise

            for block in response.content:
                if block.type == "tool_use" and block.name == "respond":
                    return response_model.model_validate(block.input)

            raise RuntimeError("LLM did not return a tool_use block named 'respond'")

        raise RuntimeError("Exhausted retries without a successful response")
