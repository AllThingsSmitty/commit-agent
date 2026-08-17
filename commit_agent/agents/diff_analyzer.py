from pathlib import Path
from pydantic import BaseModel

from ..llm_service import LLMService
from ..models import FileChange, AnnotatedChange


class FileSummary(BaseModel):
    path: str
    summary: str


class DiffAnalysisResponse(BaseModel):
    file_summaries: list[FileSummary]


_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "diff_analyzer.txt"


class DiffAnalyzer:
    def __init__(self, llm: LLMService):
        self.llm = llm
        self._prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")

    def analyze(self, changes: list[FileChange]) -> list[AnnotatedChange]:
        if not changes:
            return []

        changes_text = self._format_changes(changes)
        prompt = self._prompt_template.format(changes=changes_text)

        response = self.llm.complete_structured(prompt, DiffAnalysisResponse)

        summary_map = {s.path: s.summary for s in response.file_summaries}

        return [
            AnnotatedChange(
                file=change,
                summary=summary_map.get(change.path, "No summary available"),
            )
            for change in changes
        ]

    def _format_changes(self, changes: list[FileChange]) -> str:
        parts = []
        for change in changes:
            status_label = change.status.value.upper()
            header = f"[{status_label}] {change.path}"
            if change.is_binary:
                parts.append(f"{header}\n(binary file — no diff available)")
            else:
                parts.append(f"{header}\n```diff\n{change.diff}\n```")
        return "\n\n".join(parts)
