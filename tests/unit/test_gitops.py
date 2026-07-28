"""Tests for nexus_cli.core.gitops — shared machinery for `nexus upgrade`
and `nexus rollback` (PRD §7.9, §7.10).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus_cli.core import gitops
from nexus_cli.core.config import NexusConfig
from nexus_cli.core.output import NexusError

VALID_YAML = """
app:
  name: my-app
  image: myrepo/app:v1
  port: 8080
  healthPath: /health
platform:
  repoURL: https://github.com/user/repo.git
  branch: main
"""


def test_set_image_in_config_replaces_value_preserving_rest() -> None:
    new_text = gitops.set_image_in_config(VALID_YAML, "myrepo/app:v2")
    assert "image: myrepo/app:v2" in new_text
    assert "image: myrepo/app:v1" not in new_text
    # everything else untouched
    assert "name: my-app" in new_text
    assert "port: 8080" in new_text


def test_set_image_in_config_preserves_comments() -> None:
    text = "# a comment\napp:\n  image: myrepo/app:v1  # trailing note\n"
    new_text = gitops.set_image_in_config(text, "myrepo/app:v2")
    assert "# a comment" in new_text
    assert "image: myrepo/app:v2" in new_text


def test_set_image_in_config_raises_when_no_image_field() -> None:
    with pytest.raises(ValueError, match="no 'image:' field"):
        gitops.set_image_in_config("app:\n  name: my-app\n", "myrepo/app:v2")


def test_set_image_in_config_only_replaces_first_match() -> None:
    # a defensive check: even if "image:" appeared twice, only the first is touched
    text = "app:\n  image: myrepo/app:v1\nother:\n  image: unrelated:v1\n"
    new_text = gitops.set_image_in_config(text, "myrepo/app:v2")
    assert "image: myrepo/app:v2" in new_text
    assert "image: unrelated:v1" in new_text


def test_image_at_commit_parses_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitops.git, "show_file_at_commit", lambda *a, **k: VALID_YAML)
    assert gitops.image_at_commit("abc123") == "myrepo/app:v1"


def test_image_at_commit_none_when_commit_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitops.git, "show_file_at_commit", lambda *a, **k: None)
    assert gitops.image_at_commit("bogus") is None


def test_image_at_commit_none_when_yaml_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitops.git, "show_file_at_commit", lambda *a, **k: "not: valid: yaml: [")
    assert gitops.image_at_commit("abc123") is None


def test_image_at_commit_none_when_not_a_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitops.git, "show_file_at_commit", lambda *a, **k: "- just\n- a\n- list\n")
    assert gitops.image_at_commit("abc123") is None


def test_write_manifests_writes_files_and_skips_argocd_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = NexusConfig.model_validate(
        {
            "app": {
                "name": "my-app",
                "image": "myrepo/app:v1",
                "port": 8080,
                "healthPath": "/health",
            },
            "platform": {"repoURL": "https://github.com/user/repo.git", "branch": "main"},
        }
    )
    gitops.write_manifests(cfg)

    written = {p.name for p in (tmp_path / "k8s").iterdir()}
    assert "argocd-app.yaml" not in written
    assert "deployment.yaml" in written
    assert "service.yaml" in written
    assert "namespace.yaml" in written
    assert "myrepo/app:v1" in (tmp_path / "k8s" / "deployment.yaml").read_text()


def test_summarize_pods_parses_name_and_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {
        "items": [
            {"metadata": {"name": "my-app-abc"}, "status": {"phase": "Running"}},
            {"metadata": {"name": "my-app-def"}, "status": {}},
        ]
    }
    monkeypatch.setattr(gitops.kubectl, "get_json", lambda *a, **k: doc)
    assert gitops.summarize_pods("my-app") == [
        ("my-app-abc", "Running"),
        ("my-app-def", "Unknown"),
    ]


def test_summarize_pods_empty_when_no_pods(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitops.kubectl, "get_json", lambda *a, **k: {"items": []})
    assert gitops.summarize_pods("my-app") == []


def _cfg(**overrides: str) -> NexusConfig:
    data = {
        "app": {
            "name": "my-app",
            "image": "myrepo/app:v1",
            "port": 8080,
            "healthPath": "/health",
        },
        "platform": {
            "repoURL": "https://github.com/user/repo.git",
            "branch": overrides.get("branch", "main"),
        },
    }
    return NexusConfig.model_validate(data)


# --- check_git_preconditions ---


def test_check_git_preconditions_raises_when_not_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitops.git, "is_repo", lambda: False)
    with pytest.raises(NexusError, match="not a git repository"):
        gitops.check_git_preconditions(_cfg())


def test_check_git_preconditions_raises_when_dirty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitops.git, "is_repo", lambda: True)
    monkeypatch.setattr(gitops.git, "is_working_tree_clean", lambda: False)
    with pytest.raises(NexusError, match="uncommitted changes"):
        gitops.check_git_preconditions(_cfg())


def test_check_git_preconditions_raises_when_no_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitops.git, "is_repo", lambda: True)
    monkeypatch.setattr(gitops.git, "is_working_tree_clean", lambda: True)
    monkeypatch.setattr(gitops.git, "current_branch", lambda: "main")
    monkeypatch.setattr(gitops.git, "default_remote", lambda: None)
    with pytest.raises(NexusError, match="No git remote"):
        gitops.check_git_preconditions(_cfg())


def test_check_git_preconditions_reports_branch_mismatch_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gitops.git, "is_repo", lambda: True)
    monkeypatch.setattr(gitops.git, "is_working_tree_clean", lambda: True)
    monkeypatch.setattr(gitops.git, "current_branch", lambda: "feature-branch")
    monkeypatch.setattr(gitops.git, "default_remote", lambda: "origin")

    pre = gitops.check_git_preconditions(_cfg())  # platform.branch defaults to "main"
    assert pre.branch_matches is False
    assert pre.branch == "feature-branch"
    assert pre.remote == "origin"


def test_check_git_preconditions_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitops.git, "is_repo", lambda: True)
    monkeypatch.setattr(gitops.git, "is_working_tree_clean", lambda: True)
    monkeypatch.setattr(gitops.git, "current_branch", lambda: "main")
    monkeypatch.setattr(gitops.git, "default_remote", lambda: "origin")

    pre = gitops.check_git_preconditions(_cfg())
    assert pre.branch_matches is True
    assert pre.remote == "origin"


# --- build_validated_config ---


def test_build_validated_config_happy_path() -> None:
    new_text, new_cfg = gitops.build_validated_config(VALID_YAML, "myrepo/app:v2")
    assert "image: myrepo/app:v2" in new_text
    assert new_cfg.app.image == "myrepo/app:v2"


def test_build_validated_config_raises_on_bad_image_format() -> None:
    with pytest.raises(NexusError) as exc_info:
        gitops.build_validated_config(VALID_YAML, "no-tag-here")
    assert "app.image" in (exc_info.value.why or "")


def test_build_validated_config_raises_when_no_image_field() -> None:
    with pytest.raises(NexusError, match="Could not update the image"):
        gitops.build_validated_config("app:\n  name: my-app\n", "myrepo/app:v2")


# --- apply_image_change ---


def test_apply_image_change_writes_commits_and_pushes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = _cfg()
    new_text, new_cfg = gitops.build_validated_config(VALID_YAML, "myrepo/app:v2")

    calls: dict[str, object] = {}
    monkeypatch.setattr(gitops.git, "add", lambda paths, **k: calls.setdefault("add", paths))
    monkeypatch.setattr(gitops.git, "has_staged_changes", lambda: True)
    monkeypatch.setattr(gitops.git, "commit", lambda msg, **k: calls.setdefault("commit", msg))
    monkeypatch.setattr(
        gitops.git, "push", lambda remote, branch, **k: calls.setdefault("push", (remote, branch))
    )

    committed = gitops.apply_image_change(
        new_text,
        new_cfg,
        config_path="nexus.yaml",
        remote="origin",
        branch=cfg.platform.branch,
        commit_message="nexus: upgrade image to myrepo/app:v2",
    )

    assert committed is True
    assert (tmp_path / "nexus.yaml").read_text() == new_text
    assert (tmp_path / "k8s" / "deployment.yaml").exists()
    assert calls["add"] == ["nexus.yaml", gitops.MANIFESTS_DIR]
    assert calls["commit"] == "nexus: upgrade image to myrepo/app:v2"
    assert calls["push"] == ("origin", "main")


def test_apply_image_change_returns_false_when_nothing_staged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    new_text, new_cfg = gitops.build_validated_config(VALID_YAML, "myrepo/app:v2")

    monkeypatch.setattr(gitops.git, "add", lambda paths, **k: None)
    monkeypatch.setattr(gitops.git, "has_staged_changes", lambda: False)

    committed = gitops.apply_image_change(
        new_text,
        new_cfg,
        config_path="nexus.yaml",
        remote="origin",
        branch="main",
        commit_message="nexus: upgrade image to myrepo/app:v2",
    )
    assert committed is False
