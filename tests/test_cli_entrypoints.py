"""
Verify CLI entry points are importable and accept --help without crashing.
"""

import subprocess
import sys
import pytest
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)


def _run(args, timeout=15):
    return subprocess.run(
        args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout,
    )


class TestOhCLI:

    def test_oh_importable(self):
        r = _run([sys.executable, "-c", "import sys; sys.path.insert(0, '.'); import oh"])
        assert r.returncode != 2, f"Import error:\n{r.stderr}"

    def test_oh_help(self):
        r = _run([sys.executable, "oh.py", "--help"])
        assert r.returncode == 0
        assert "--no-wiggum" in r.stdout or "--no-wiggum" in r.stderr


class TestLitReviewCLI:

    def test_lit_review_help(self):
        r = _run([sys.executable, "-m", "harness.skills.lit_review_skill", "--help"])
        assert r.returncode == 0
        assert "--max-fetch" in r.stdout
        assert "--template" in r.stdout
        assert "--producer" in r.stdout
        assert "--no-wiggum" in r.stdout

    def test_valid_templates_listed(self):
        r = _run([sys.executable, "-m", "harness.skills.lit_review_skill", "--help"])
        assert "survey" in r.stdout
        assert "gaps" in r.stdout
        assert "executive" in r.stdout


class TestApiServer:

    def test_server_module_importable(self):
        r = _run([sys.executable, "-c", "from harness.api.main import app; assert app"])
        assert r.returncode == 0, f"Import error:\n{r.stderr}"


class TestModuleImports:

    @pytest.mark.parametrize("module", [
        "harness.skills",
        "harness.schema",
        "harness.security",
        "harness.inference",
        "harness.config",
        "harness.wiggum",
        "harness.summarizer",
    ])
    def test_import(self, module):
        r = _run([sys.executable, "-c", f"import {module}"])
        assert r.returncode == 0, f"Failed to import {module}:\n{r.stderr}"
