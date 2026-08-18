import git
import pytest

from commit_agent.git_service import GitService
from commit_agent.models import CommitGroup, CommitType, FileStatus


@pytest.fixture
def repo(tmp_path):
    """Minimal git repo with one initial commit so HEAD always exists."""
    r = git.Repo.init(tmp_path)
    r.config_writer().set_value("user", "name", "Test User").release()
    r.config_writer().set_value("user", "email", "test@example.com").release()
    (tmp_path / "init.txt").write_text("initial")
    r.index.add(["init.txt"])
    r.index.commit("Initial commit")
    return tmp_path


def _svc(repo_path) -> GitService:
    return GitService(repo_path)


def _group(files, subject="test commit", commit_type=CommitType.feat) -> CommitGroup:
    return CommitGroup(files=files, commit_type=commit_type, subject=subject)


class TestGetChanges:
    def test_clean_repo_returns_empty(self, repo):
        assert _svc(repo).get_changes() == []

    def test_detects_staged_new_file(self, repo):
        (repo / "hello.py").write_text("print('hello')")
        git.Repo(repo).index.add(["hello.py"])

        changes = _svc(repo).get_changes()

        assert len(changes) == 1
        assert changes[0].path == "hello.py"
        assert changes[0].status == FileStatus.added
        assert changes[0].is_staged is True

    def test_detects_unstaged_modification(self, repo):
        r = git.Repo(repo)
        (repo / "hello.py").write_text("v1")
        r.index.add(["hello.py"])
        r.index.commit("add hello")
        (repo / "hello.py").write_text("v2")  # not staged

        changes = _svc(repo).get_changes()

        assert len(changes) == 1
        assert changes[0].path == "hello.py"
        assert changes[0].is_staged is False

    def test_detects_untracked_file(self, repo):
        (repo / "new.txt").write_text("untracked")

        changes = _svc(repo).get_changes()

        paths = [c.path for c in changes]
        assert "new.txt" in paths
        fc = next(c for c in changes if c.path == "new.txt")
        assert fc.status == FileStatus.untracked

    def test_staged_only_excludes_unstaged_files(self, repo):
        r = git.Repo(repo)
        (repo / "a.py").write_text("a=1")
        r.index.add(["a.py"])
        r.index.commit("add a")
        (repo / "a.py").write_text("a=2")  # unstaged modification

        (repo / "b.py").write_text("b=1")
        r.index.add(["b.py"])  # staged new file

        changes = _svc(repo).get_changes(staged_only=True)

        paths = [c.path for c in changes]
        assert "b.py" in paths
        assert "a.py" not in paths

    def test_staged_only_returns_staged_changes(self, repo):
        r = git.Repo(repo)
        (repo / "staged.py").write_text("staged")
        r.index.add(["staged.py"])

        changes = _svc(repo).get_changes(staged_only=True)

        assert len(changes) == 1
        assert changes[0].path == "staged.py"
        assert changes[0].is_staged is True

    def test_staged_file_not_duplicated_in_unstaged(self, repo):
        r = git.Repo(repo)
        (repo / "both.py").write_text("staged version")
        r.index.add(["both.py"])

        changes = _svc(repo).get_changes()
        paths = [c.path for c in changes]

        assert paths.count("both.py") == 1


class TestCommitGroup:
    def test_basic_commit_creates_commit(self, repo):
        r = git.Repo(repo)
        (repo / "feature.py").write_text("def f(): pass")
        r.index.add(["feature.py"])

        sha = _svc(repo).commit_group(_group(["feature.py"]))

        assert len(sha) == 40
        assert r.head.commit.message == "feat: test commit"

    def test_does_not_commit_unstaged_hunks(self, repo):
        r = git.Repo(repo)
        (repo / "file.py").write_text("line1\n")
        r.index.add(["file.py"])
        r.index.commit("add file")

        # Stage a change
        (repo / "file.py").write_text("line1\nstaged_line\n")
        r.index.add(["file.py"])

        # Add an unstaged change on top
        (repo / "file.py").write_text("line1\nstaged_line\nunstaged_line\n")

        _svc(repo).commit_group(_group(["file.py"]))

        blob = r.head.commit.tree["file.py"]
        content = blob.data_stream.read().decode()
        assert "staged_line" in content
        assert "unstaged_line" not in content

    def test_multi_group_only_commits_group_files(self, repo):
        r = git.Repo(repo)
        (repo / "a.py").write_text("a")
        (repo / "b.py").write_text("b")
        r.index.add(["a.py", "b.py"])

        svc = _svc(repo)
        svc.commit_group(_group(["a.py"], subject="add a"))

        # After first commit, only a.py is in HEAD (besides init.txt)
        first_paths = {item.path for item in r.head.commit.tree}
        assert "a.py" in first_paths
        assert "b.py" not in first_paths

    def test_multi_group_second_commit_includes_restored_files(self, repo):
        r = git.Repo(repo)
        (repo / "a.py").write_text("a")
        (repo / "b.py").write_text("b")
        r.index.add(["a.py", "b.py"])

        svc = _svc(repo)
        svc.commit_group(_group(["a.py"], subject="add a"))
        svc.commit_group(_group(["b.py"], subject="add b"))

        final_paths = {item.path for item in r.head.commit.tree}
        assert "a.py" in final_paths
        assert "b.py" in final_paths

    def test_custom_message_overrides_format(self, repo):
        r = git.Repo(repo)
        (repo / "x.py").write_text("x")
        r.index.add(["x.py"])

        _svc(repo).commit_group(_group(["x.py"]), custom_message="my custom message")

        assert r.head.commit.message == "my custom message"

    def test_non_conventional_message(self, repo):
        r = git.Repo(repo)
        (repo / "y.py").write_text("y")
        r.index.add(["y.py"])

        group = CommitGroup(files=["y.py"], commit_type=CommitType.feat, subject="plain subject")
        _svc(repo).commit_group(group, conventional=False)

        assert r.head.commit.message == "plain subject"


class TestProperties:
    def test_current_branch_is_string(self, repo):
        svc = _svc(repo)
        assert isinstance(svc.current_branch, str)
        assert len(svc.current_branch) > 0

    def test_has_no_conflicts_on_clean_repo(self, repo):
        assert _svc(repo).has_conflicts() is False

    def test_invalid_repo_raises_runtime_error(self, tmp_path):
        with pytest.raises(RuntimeError, match="No git repository"):
            GitService(tmp_path)
