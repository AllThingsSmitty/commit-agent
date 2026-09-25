from pathlib import Path
from pydantic import BaseModel

from . import load_prompt_template
from ..llm_service import LLMService
from ..models import FileChange, RiskFlag, RiskSeverity


class RiskFlagResponse(BaseModel):
    severity: str
    message: str
    affected_files: list[str]


class RiskReviewResponse(BaseModel):
    flags: list[RiskFlagResponse]


_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "risk_reviewer.txt"


class RiskReviewer:
    def __init__(self, llm: LLMService):
        self.llm = llm
        self._prompt_template = load_prompt_template(_PROMPT_PATH)

    def review(self, changes: list[FileChange]) -> list[RiskFlag]:
        if not changes:
            return []

        changes_text = self._format_changes(changes)
        prompt = self._prompt_template.format(changes=changes_text)

        response = self.llm.complete_structured(prompt, RiskReviewResponse)

        flags = []
        for flag in response.flags:
            try:
                severity = RiskSeverity(flag.severity)
            except ValueError:
                severity = RiskSeverity.low

            flags.append(
                RiskFlag(
                    severity=severity,
                    message=flag.message,
                    affected_files=flag.affected_files,
                )
            )

        return flags

    def _format_changes(self, changes: list[FileChange]) -> str:
        parts = []
        for change in changes:
            status_label = change.status.value.upper()
            header = f"[{status_label}] {change.path}"
            if change.is_binary:
                parts.append(f"{header}\n(binary file)")
            else:
                parts.append(f"{header}\n```diff\n{change.diff}\n```")
        return "\n\n".join(parts)
