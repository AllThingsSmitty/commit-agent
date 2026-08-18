from unittest.mock import MagicMock

import pytest

from commit_agent.agents.diff_analyzer import DiffAnalyzer, DiffAnalysisResponse, FileSummary
from commit_agent.agents.commit_planner import CommitPlanner, CommitPlanResponse, CommitGroupPlan
from commit_agent.agents.message_writer import MessageWriter, CommitMessageResponse
from commit_agent.agents.risk_reviewer import RiskReviewer, RiskReviewResponse, RiskFlagResponse
from commit_agent.llm_service import LLMService
from commit_agent.models import (
    AnnotatedChange, CommitType, FileChange, FileStatus, RiskSeverity,
)


def _llm() -> LLMService:
    return MagicMock(spec=LLMService)


def _file_change(path="src/main.py", diff="+new line", is_staged=True) -> FileChange:
    return FileChange(
        path=path,
        status=FileStatus.added,
        diff=diff,
        is_staged=is_staged,
        size_bytes=100,
        is_binary=False,
    )


def _annotated(path="src/main.py") -> AnnotatedChange:
    return AnnotatedChange(file=_file_change(path=path), summary=f"Summary of {path}")


# ---------------------------------------------------------------------------
# DiffAnalyzer
# ---------------------------------------------------------------------------

class TestDiffAnalyzer:
    def test_analyze_maps_summary_to_change(self):
        llm = _llm()
        llm.complete_structured.return_value = DiffAnalysisResponse(
            file_summaries=[FileSummary(path="src/main.py", summary="Adds entry point")]
        )

        result = DiffAnalyzer(llm).analyze([_file_change()])

        assert len(result) == 1
        assert result[0].file.path == "src/main.py"
        assert result[0].summary == "Adds entry point"

    def test_analyze_falls_back_when_path_missing_from_response(self):
        llm = _llm()
        llm.complete_structured.return_value = DiffAnalysisResponse(file_summaries=[])

        result = DiffAnalyzer(llm).analyze([_file_change()])

        assert result[0].summary == "No summary available"

    def test_analyze_empty_input_skips_llm(self):
        llm = _llm()
        assert DiffAnalyzer(llm).analyze([]) == []
        llm.complete_structured.assert_not_called()

    def test_analyze_preserves_input_order(self):
        llm = _llm()
        # LLM returns summaries in reverse order
        llm.complete_structured.return_value = DiffAnalysisResponse(
            file_summaries=[
                FileSummary(path="b.py", summary="B"),
                FileSummary(path="a.py", summary="A"),
            ]
        )

        result = DiffAnalyzer(llm).analyze([_file_change("a.py"), _file_change("b.py")])

        assert result[0].file.path == "a.py"
        assert result[0].summary == "A"
        assert result[1].file.path == "b.py"
        assert result[1].summary == "B"

    def test_analyze_multiple_files(self):
        llm = _llm()
        llm.complete_structured.return_value = DiffAnalysisResponse(
            file_summaries=[
                FileSummary(path="a.py", summary="A"),
                FileSummary(path="b.py", summary="B"),
                FileSummary(path="c.py", summary="C"),
            ]
        )

        result = DiffAnalyzer(llm).analyze([
            _file_change("a.py"), _file_change("b.py"), _file_change("c.py")
        ])

        assert len(result) == 3


# ---------------------------------------------------------------------------
# CommitPlanner
# ---------------------------------------------------------------------------

class TestCommitPlanner:
    def test_plan_returns_groups(self):
        llm = _llm()
        llm.complete_structured.return_value = CommitPlanResponse(
            groups=[CommitGroupPlan(files=["src/main.py"], rationale="new feature")]
        )

        result = CommitPlanner(llm).plan([_annotated()])

        assert len(result) == 1
        assert result[0].files == ["src/main.py"]
        assert result[0].rationale == "new feature"

    def test_plan_empty_input_skips_llm(self):
        llm = _llm()
        assert CommitPlanner(llm).plan([]) == []
        llm.complete_structured.assert_not_called()

    def test_plan_multiple_groups(self):
        llm = _llm()
        llm.complete_structured.return_value = CommitPlanResponse(
            groups=[
                CommitGroupPlan(files=["a.py"], rationale="feature A"),
                CommitGroupPlan(files=["b.py"], rationale="feature B"),
            ]
        )

        result = CommitPlanner(llm).plan([_annotated("a.py"), _annotated("b.py")])

        assert len(result) == 2
        assert result[0].files == ["a.py"]
        assert result[1].files == ["b.py"]

    def test_plan_single_call_regardless_of_file_count(self):
        llm = _llm()
        llm.complete_structured.return_value = CommitPlanResponse(groups=[])

        CommitPlanner(llm).plan([_annotated("a.py"), _annotated("b.py"), _annotated("c.py")])

        assert llm.complete_structured.call_count == 1


# ---------------------------------------------------------------------------
# MessageWriter
# ---------------------------------------------------------------------------

class TestMessageWriter:
    def test_write_returns_commit_group(self):
        llm = _llm()
        llm.complete_structured.return_value = CommitMessageResponse(
            commit_type="feat", scope="auth", subject="add login", breaking_change=False
        )

        plan = [CommitGroupPlan(files=["auth.py"], rationale="auth")]
        result = MessageWriter(llm).write(plan, [_annotated("auth.py")])

        assert len(result) == 1
        assert result[0].commit_type == CommitType.feat
        assert result[0].scope == "auth"
        assert result[0].subject == "add login"
        assert result[0].format_message() == "feat(auth): add login"

    def test_write_falls_back_to_chore_for_unknown_type(self):
        llm = _llm()
        llm.complete_structured.return_value = CommitMessageResponse(
            commit_type="invalid_type", subject="some change"
        )

        plan = [CommitGroupPlan(files=["x.py"], rationale="x")]
        result = MessageWriter(llm).write(plan, [_annotated("x.py")])

        assert result[0].commit_type == CommitType.chore

    def test_write_empty_plan_skips_llm(self):
        llm = _llm()
        assert MessageWriter(llm).write([], []) == []
        llm.complete_structured.assert_not_called()

    def test_write_preserves_plan_order_with_parallel_execution(self):
        # Use a function side_effect so each call returns a response tied to its
        # file path, ensuring order is checked independently of thread scheduling.
        subject_map = {"a.py": "first", "b.py": "second", "c.py": "third"}

        def _respond(prompt, response_model):
            for path, subject in subject_map.items():
                if path in prompt:
                    return CommitMessageResponse(commit_type="feat", subject=subject)
            return CommitMessageResponse(commit_type="chore", subject="unknown")

        llm = _llm()
        llm.complete_structured.side_effect = _respond

        plan = [
            CommitGroupPlan(files=["a.py"], rationale="a"),
            CommitGroupPlan(files=["b.py"], rationale="b"),
            CommitGroupPlan(files=["c.py"], rationale="c"),
        ]
        annotated = [_annotated("a.py"), _annotated("b.py"), _annotated("c.py")]
        result = MessageWriter(llm).write(plan, annotated)

        assert result[0].subject == "first"
        assert result[1].subject == "second"
        assert result[2].subject == "third"

    def test_write_breaking_change_propagated(self):
        llm = _llm()
        llm.complete_structured.return_value = CommitMessageResponse(
            commit_type="feat", subject="big change", breaking_change=True
        )

        plan = [CommitGroupPlan(files=["api.py"], rationale="breaking")]
        result = MessageWriter(llm).write(plan, [_annotated("api.py")])

        assert result[0].breaking_change is True
        assert result[0].format_message() == "feat!: big change"


# ---------------------------------------------------------------------------
# RiskReviewer
# ---------------------------------------------------------------------------

class TestRiskReviewer:
    def test_review_returns_flags(self):
        llm = _llm()
        llm.complete_structured.return_value = RiskReviewResponse(
            flags=[RiskFlagResponse(
                severity="high",
                message="Potential secret exposure",
                affected_files=["config.py"],
            )]
        )

        result = RiskReviewer(llm).review([_file_change("config.py")])

        assert len(result) == 1
        assert result[0].severity == RiskSeverity.high
        assert result[0].message == "Potential secret exposure"
        assert result[0].affected_files == ["config.py"]

    def test_review_falls_back_to_low_for_unknown_severity(self):
        llm = _llm()
        llm.complete_structured.return_value = RiskReviewResponse(
            flags=[RiskFlagResponse(severity="critical", message="risky", affected_files=[])]
        )

        result = RiskReviewer(llm).review([_file_change()])

        assert result[0].severity == RiskSeverity.low

    def test_review_empty_input_skips_llm(self):
        llm = _llm()
        assert RiskReviewer(llm).review([]) == []
        llm.complete_structured.assert_not_called()

    def test_review_no_flags(self):
        llm = _llm()
        llm.complete_structured.return_value = RiskReviewResponse(flags=[])

        result = RiskReviewer(llm).review([_file_change()])

        assert result == []

    def test_review_multiple_flags(self):
        llm = _llm()
        llm.complete_structured.return_value = RiskReviewResponse(
            flags=[
                RiskFlagResponse(severity="high", message="flag1", affected_files=["a.py"]),
                RiskFlagResponse(severity="medium", message="flag2", affected_files=["b.py"]),
                RiskFlagResponse(severity="low", message="flag3", affected_files=[]),
            ]
        )

        result = RiskReviewer(llm).review([_file_change("a.py"), _file_change("b.py")])

        assert len(result) == 3
        assert result[0].severity == RiskSeverity.high
        assert result[1].severity == RiskSeverity.medium
        assert result[2].severity == RiskSeverity.low
