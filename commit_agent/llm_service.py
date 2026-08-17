from typing import Type, TypeVar
import anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMService:
    def __init__(self, model: str = "claude-opus-5", max_tokens: int = 4096):
        self.client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def complete_structured(self, prompt: str, response_model: Type[T]) -> T:
        schema = response_model.model_json_schema()

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

        for block in response.content:
            if block.type == "tool_use" and block.name == "respond":
                return response_model.model_validate(block.input)

        raise RuntimeError("LLM did not return a tool_use block named 'respond'")
