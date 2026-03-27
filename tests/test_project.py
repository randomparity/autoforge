"""Tests for project scaffolding."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from autoforge.agent.project import (
    init_project,
    list_projects,
    switch_project,
    validate_project_name,
)


class TestValidateProjectName:
    def test_valid(self) -> None:
        validate_project_name("dpdk")
        validate_project_name("my-project")
        validate_project_name("v2")

    def test_uppercase_rejected(self) -> None:
        with pytest.raises(ValueError, match="lowercase"):
            validate_project_name("MyProject")

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="lowercase"):
            validate_project_name("")

    def test_leading_hyphen_rejected(self) -> None:
        with pytest.raises(ValueError, match="lowercase"):
            validate_project_name("-bad")


class TestInitProject:
    def test_creates_skeleton(self, tmp_path: Path) -> None:
        with (
            patch("autoforge.agent.project.REPO_ROOT", tmp_path),
            patch("autoforge.agent.project.save_pointer"),
        ):
            pdir = init_project("vllm")

        assert pdir == tmp_path / "projects" / "vllm"
        assert (pdir / "builds").is_dir()
        assert (pdir / "deploys").is_dir()
        assert (pdir / "tests").is_dir()
        assert (pdir / "perfs").is_dir()
        assert (pdir / "judges").is_dir()
        assert (pdir / "sprints").is_dir()

    def test_duplicate_raises(self, tmp_path: Path) -> None:
        (tmp_path / "projects" / "dpdk").mkdir(parents=True)

        with (
            patch("autoforge.agent.project.REPO_ROOT", tmp_path),
            pytest.raises(FileExistsError, match="already exists"),
        ):
            init_project("dpdk")

    def test_invalid_name_raises(self) -> None:
        with pytest.raises(ValueError, match="lowercase"):
            init_project("BAD_NAME")


class TestListProjects:
    def test_no_projects_dir(self, tmp_path: Path) -> None:
        with patch("autoforge.agent.project.REPO_ROOT", tmp_path):
            assert list_projects() == []

    def test_empty_projects_dir(self, tmp_path: Path) -> None:
        (tmp_path / "projects").mkdir()
        with patch("autoforge.agent.project.REPO_ROOT", tmp_path):
            assert list_projects() == []

    def test_returns_sorted_project_names(self, tmp_path: Path) -> None:
        for name in ("vllm", "dpdk", "kernel"):
            (tmp_path / "projects" / name).mkdir(parents=True)
        with patch("autoforge.agent.project.REPO_ROOT", tmp_path):
            assert list_projects() == ["dpdk", "kernel", "vllm"]

    def test_ignores_files(self, tmp_path: Path) -> None:
        projects = tmp_path / "projects"
        projects.mkdir()
        (projects / "dpdk").mkdir()
        (projects / "README.md").write_text("not a project")
        with patch("autoforge.agent.project.REPO_ROOT", tmp_path):
            assert list_projects() == ["dpdk"]


class TestSwitchProject:
    def test_switch_to_existing_clears_sprint(self, tmp_path: Path) -> None:
        (tmp_path / "projects" / "dpdk").mkdir(parents=True)
        with (
            patch("autoforge.agent.project.REPO_ROOT", tmp_path),
            patch("autoforge.agent.project.save_pointer") as mock_save,
        ):
            switch_project("dpdk")

        mock_save.assert_called_once_with("dpdk", "")

    def test_nonexistent_project_raises(self, tmp_path: Path) -> None:
        (tmp_path / "projects").mkdir()
        with (
            patch("autoforge.agent.project.REPO_ROOT", tmp_path),
            pytest.raises(FileNotFoundError, match="Project not found"),
        ):
            switch_project("nonexistent")

    def test_invalid_name_raises(self) -> None:
        with pytest.raises(ValueError, match="lowercase"):
            switch_project("Bad Name")
