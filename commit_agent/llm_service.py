import time
from typing import Type, TypeVar
import anthropic
from pydantic import BaseModel, ValidationError

from .logging_config import get_logger

T = TypeVar("T", bound=BaseModel)
logger = get_logger("llm_service")

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
            msg = (
                f"Prompt is {len(prompt):,} chars (~{len(prompt) // _CHARS_PER_TOKEN:,} tokens), "
                f"which exceeds the {_MAX_PROMPT_CHARS // _CHARS_PER_TOKEN:,}-token safety limit. "
                "Reduce the number of files or lower DIFF_TRUNCATE_CHARS."
            )
            logger.error(msg)
            raise ValueError(msg)

        schema = response_model.model_json_schema()
        logger.debug(f"Calling LLM with model={self.model}, max_tokens={self.max_tokens}")

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
                logger.debug(f"LLM call succeeded on attempt {attempt + 1}")
            except anthropic.RateLimitError as exc:
                if attempt == _MAX_RETRIES - 1:
                    logger.error(f"Rate limited - exhausted {_MAX_RETRIES} retries")
                    raise
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning(f"Rate limited, retrying after {delay}s (attempt {attempt + 1}/{_MAX_RETRIES})")
                time.sleep(delay)
                continue
            except anthropic.APIStatusError as exc:
                if exc.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY * (2 ** attempt)
                    logger.warning(f"API error {exc.status_code}, retrying after {delay}s (attempt {attempt + 1}/{_MAX_RETRIES})")
                    time.sleep(delay)
                    continue
                logger.error(f"API error {exc.status_code}: {exc}")
                raise

            for block in response.content:
                if block.type == "tool_use" and block.name == "respond":
                    try:
                        result = response_model.model_validate(block.input)
                        logger.debug(f"Successfully parsed response into {response_model.__name__}")
                        return result
                    except ValidationError as e:
                        logger.error(f"Failed to validate LLM response: {e}")
                        raise

            logger.error("LLM did not return a tool_use block named 'respond'")
            raise RuntimeError("LLM did not return a tool_use block named 'respond'")

        logger.error("Exhausted retries without a successful response")
        raise RuntimeError("Exhausted retries without a successful response")
