from pathlib import Path
from pydantic import BaseModel
from typing import Optional

from ..llm_service import LLMService
from ..models import AnnotatedChange, CommitGroup, CommitType
from .commit_planner import CommitGroupPlan


class CommitMessageResponse(BaseModel):
    commit_type: str
    scope: Optional[str] = None
    subject: str
    body: Optional[str] = None
    breaking_change: bool = False


_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "message_writer.txt"


class MessageWriter:
    def __init__(self, llm: LLMService):
        self.llm = llm
        self._prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")

    def write(
        self,
        plan: list[CommitGroupPlan],
        annotated_changes: list[AnnotatedChange],
    ) -> list[CommitGroup]:
        if not plan:
            return []

        summary_map = {ac.file.path: ac.summary for ac in annotated_changes}
        groups = []

        for group_plan in plan:
            files_list = "\n".join(f"- {f}" for f in group_plan.files)
            summaries_list = "\n".join(
                f"- {f}: {summary_map.get(f, 'no summary')}"
                for f in group_plan.files
            )

            prompt = self._prompt_template.format(
                files=files_list,
                summaries=summaries_list,
                rationale=group_plan.rationale,
            )

            response = self.llm.complete_structured(prompt, CommitMessageResponse)

            # Normalize commit type; fall back to chore on unknown value
            try:
                commit_type = CommitType(response.commit_type)
            except ValueError:
                commit_type = CommitType.chore

            groups.append(
                CommitGroup(
                    files=group_plan.files,
                    commit_type=commit_type,
                    scope=response.scope,
                    subject=response.subject,
                    body=response.body,
                    breaking_change=response.breaking_change,
                )
            )

        return groups
