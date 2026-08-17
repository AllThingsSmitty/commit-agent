from pathlib import Path
from pydantic import BaseModel

from ..llm_service import LLMService
from ..models import AnnotatedChange


class CommitGroupPlan(BaseModel):
    files: list[str]
    rationale: str


class CommitPlanResponse(BaseModel):
    groups: list[CommitGroupPlan]


_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "commit_planner.txt"


class CommitPlanner:
    def __init__(self, llm: LLMService):
        self.llm = llm
        self._prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")

    def plan(self, annotated_changes: list[AnnotatedChange]) -> list[CommitGroupPlan]:
        if not annotated_changes:
            return []

        changes_text = self._format_changes(annotated_changes)
        prompt = self._prompt_template.format(annotated_changes=changes_text)

        response = self.llm.complete_structured(prompt, CommitPlanResponse)
        return response.groups

    def _format_changes(self, annotated_changes: list[AnnotatedChange]) -> str:
        parts = []
        for ac in annotated_changes:
            staged = "staged" if ac.file.is_staged else "unstaged"
            parts.append(
                f"- {ac.file.path} ({ac.file.status.value}, {staged})\n  {ac.summary}"
            )
        return "\n".join(parts)
