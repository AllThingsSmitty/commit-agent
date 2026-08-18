import pytest
from commit_agent.models import CommitGroup, CommitType


def _make_group(**kwargs) -> CommitGroup:
    defaults = dict(
        files=["src/main.py"],
        commit_type=CommitType.feat,
        subject="add user authentication",
    )
    defaults.update(kwargs)
    return CommitGroup(**defaults)


def test_format_message_minimal():
    group = _make_group()
    assert group.format_message() == "feat: add user authentication"


def test_format_message_with_scope():
    group = _make_group(scope="auth")
    assert group.format_message() == "feat(auth): add user authentication"


def test_format_message_breaking_change():
    group = _make_group(breaking_change=True)
    assert group.format_message() == "feat!: add user authentication"


def test_format_message_breaking_change_with_scope():
    group = _make_group(scope="api", breaking_change=True)
    assert group.format_message() == "feat(api)!: add user authentication"


def test_format_message_with_body():
    group = _make_group(body="Implements JWT-based login flow.")
    msg = group.format_message()
    assert msg == "feat: add user authentication\n\nImplements JWT-based login flow."


def test_format_message_fix_type():
    group = _make_group(commit_type=CommitType.fix, subject="resolve null pointer in parser")
    assert group.format_message() == "fix: resolve null pointer in parser"


def test_format_message_full():
    group = _make_group(
        commit_type=CommitType.refactor,
        scope="core",
        subject="extract validation logic",
        body="Moved validation into a dedicated module for reuse.",
        breaking_change=False,
    )
    assert group.format_message() == (
        "refactor(core): extract validation logic\n\n"
        "Moved validation into a dedicated module for reuse."
    )


def test_format_message_non_conventional_subject_only():
    group = _make_group(subject="plain commit message")
    assert group.format_message(conventional=False) == "plain commit message"


def test_format_message_non_conventional_with_body():
    group = _make_group(subject="plain message", body="Some extra detail.")
    assert group.format_message(conventional=False) == "plain message\n\nSome extra detail."


def test_format_message_non_conventional_ignores_type_and_scope():
    group = _make_group(commit_type=CommitType.fix, scope="api", subject="fix the thing")
    msg = group.format_message(conventional=False)
    assert msg == "fix the thing"
    assert "fix(" not in msg
    assert "api" not in msg


def test_format_message_non_conventional_ignores_breaking_change_marker():
    group = _make_group(subject="remove old api", breaking_change=True)
    msg = group.format_message(conventional=False)
    assert "!" not in msg
    assert msg == "remove old api"
