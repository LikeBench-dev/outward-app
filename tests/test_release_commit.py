import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


POWERSHELL = shutil.which("powershell.exe")
GIT = shutil.which("git")
BUILD_SCRIPT = Path(__file__).resolve().parents[1] / "build-installer.ps1"


@unittest.skipUnless(POWERSHELL and GIT, "Requires Windows PowerShell and Git")
class ReleaseCommitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="outward-release-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo with spaces"
        self.repo.mkdir()
        self.git("init", "--quiet")
        self.git("config", "user.name", "Release Test")
        self.git("config", "user.email", "release@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.hooks = Path(self.temp.name) / "hooks"
        self.hooks.mkdir()
        self.git("config", "core.hooksPath", str(self.hooks))
        (self.repo / "VERSION").write_text("0.1.6\n", encoding="ascii")
        (self.repo / ".gitignore").write_text("build/\n", encoding="ascii")
        (self.repo / "tracked.txt").write_text("before\n", encoding="ascii")
        (self.repo / "deleted.txt").write_text("before\n", encoding="ascii")
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "Initial")
        self.initial_head = self.git("rev-parse", "HEAD")
        self.harness = Path(self.temp.name) / "check.ps1"
        # Load the actual Git helpers without running the installer build.
        source = str(BUILD_SCRIPT).replace("'", "''")
        self.harness.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            "$tokens = $null; $errors = $null\n"
            f"$ast = [System.Management.Automation.Language.Parser]::ParseFile('{source}', [ref]$tokens, [ref]$errors)\n"
            "if ($errors.Count) { throw ($errors | Out-String) }\n"
            "$names = @('Test-AppVersion', 'Invoke-ReleaseGit', 'Assert-ReleaseCommitReady', 'New-ReleaseCommit')\n"
            "$ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -in $names }, $true) | ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }\n"
            "$Root = $args[0]; $Version = $args[1]\n"
            "Assert-ReleaseCommitReady\n"
            "if ($args[2] -eq 'commit') {\n"
            "    Set-Content -LiteralPath (Join-Path $Root 'VERSION') -Value $Version -Encoding ASCII\n"
            "    New-ReleaseCommit\n"
            "}\n",
            encoding="utf-8",
        )

    def git(self, *args):
        return subprocess.run(
            [GIT, "-C", str(self.repo), *args],
            check=True, capture_output=True, text=True, encoding="utf-8",
        ).stdout.strip()

    def release(self, version="0.1.7", action="check"):
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(self.harness), str(self.repo), version, action],
            capture_output=True, text=True,
        )

    def test_commits_version_and_all_changes_respecting_gitignore(self):
        (self.repo / "tracked.txt").write_text("after\n", encoding="ascii")
        (self.repo / "deleted.txt").unlink()
        (self.repo / "new.txt").write_text("new\n", encoding="ascii")
        (self.repo / "build").mkdir()
        (self.repo / "build" / "output.exe").write_bytes(b"ignored")
        result = self.release(action="commit")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("log", "-1", "--format=%s"), "Release v0.1.7")
        self.assertEqual(self.git("show", "HEAD:VERSION"), "0.1.7")
        changed = set(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines())
        self.assertEqual(changed, {"VERSION", "tracked.txt", "deleted.txt", "new.txt"})
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_rejects_same_or_older_version_without_mutating_repo(self):
        for version in ("0.1.6", "0.1.5"):
            with self.subTest(version=version):
                result = self.release(version, "commit")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("newer than HEAD:VERSION", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.initial_head)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_rejects_existing_local_tag(self):
        self.git("tag", "v0.1.7")
        result = self.release(action="commit")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_rejects_detached_head(self):
        self.git("checkout", "--quiet", "--detach")
        result = self.release(action="commit")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_commit_hook_failure_is_reported(self):
        (self.hooks / "pre-commit").write_text("#!/bin/sh\nexit 7\n", encoding="ascii")
        result = self.release(action="commit")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed (exit", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.initial_head)
