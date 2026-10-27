"""Black-box harness for the sb command.

Each test gets a throwaway HOME holding a side-projects folder. Git checkouts are made with git,
the CLI runs as a subprocess against the checkout's src/ tree, and records are read from
$HOME/.switchboard/switchboard.db with stdlib sqlite3 after the command has exited.
"""

import contextlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parent.parent
SRC = CHECKOUT / "src"
ENTRY = "import sys; from switchboard.cli import main; sys.exit(main(sys.argv[1:]))"
GIT_SETTINGS = (
    "-c", "user.name=sb-tests",
    "-c", "user.email=sb-tests@example.invalid",
    "-c", "commit.gpgsign=false",
    "-c", "init.defaultBranch=main",
)
COMMAND_TIMEOUT_SECONDS = 60


class Home:
    """A throwaway HOME: side-projects/ always, .switchboard/ once a command has run."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.side_projects = root / "side-projects"
        self.side_projects.mkdir()
        self.db_path = root / ".switchboard" / "switchboard.db"

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("SB_", "GIT_"))
        }
        env.update(
            HOME=str(self.root),
            XDG_CONFIG_HOME=str(self.root / ".config"),
            GIT_CONFIG_NOSYSTEM="1",
            PYTHONPATH=str(SRC),
            PYTHONDONTWRITEBYTECODE="1",
        )
        env.update(extra or {})
        return env

    def git(self, cwd: Path, *args: str) -> None:
        subprocess.run(
            ["git", *GIT_SETTINGS, *args],
            cwd=cwd,
            env=self.env(),
            check=True,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )

    def make_checkout(self, relative: str) -> Path:
        """A git checkout with one empty commit at HOME/<relative>."""
        path = self.root / relative
        path.mkdir(parents=True)
        self.git(path, "init", "-q")
        self.git(path, "commit", "-q", "--allow-empty", "-m", "init")
        return path

    def add_worktree(self, repo: Path, relative: str) -> Path:
        """A linked git worktree of repo at repo/<relative>, on a new branch."""
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        self.git(repo, "worktree", "add", "-q", "-b", "wt-" + path.name, str(path))
        return path

    def command(self, args: tuple[str, ...]) -> list[str]:
        return [sys.executable, "-P", "-c", ENTRY, *args]

    def sb(
        self, *args: str, cwd: Path, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run `sb <args>` once and return its exit code and output."""
        return subprocess.run(
            self.command(args),
            cwd=cwd,
            env=self.env(env),
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )

    def sb_ok(
        self, *args: str, cwd: Path, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        """An arrange step: run `sb <args>` and fail the test setup unless it exits 0."""
        result = self.sb(*args, cwd=cwd, env=env)
        if result.returncode != 0:
            raise AssertionError(
                f"arrange step `sb {' '.join(args)}` exited {result.returncode}: {result.stderr}"
            )
        return result

    def sb_parallel(
        self, count: int, *args: str, cwd: Path, env: dict[str, str] | None = None
    ) -> list[tuple[int, str]]:
        """Start `count` copies of `sb <args>` at once; return each (exit code, stderr)."""
        processes = [
            subprocess.Popen(
                self.command(args),
                cwd=cwd,
                env=self.env(env),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(count)
        ]
        outcomes = []
        for process in processes:
            _, stderr = process.communicate(timeout=COMMAND_TIMEOUT_SECONDS)
            outcomes.append((process.returncode, stderr))
        return outcomes

    def rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute(sql, params).fetchall()

    def pragma(self, name: str) -> object:
        return self.rows(f"PRAGMA {name}")[0][0]

    def table_names(self) -> set[str]:
        return {
            name
            for (name,) in self.rows(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    def contents(self) -> dict[str, list]:
        """Every table's rows, order-free, plus the schema version: the whole written state."""
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            names = [
                name
                for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master"
                    " WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            state = {
                name: sorted(conn.execute(f'SELECT * FROM "{name}"').fetchall(), key=repr)
                for name in names
            }
            state["PRAGMA user_version"] = conn.execute("PRAGMA user_version").fetchall()
        return state


class SbTestCase(unittest.TestCase):
    """Base for sb tests: each home is created fresh and removed after the test."""

    def make_home(self) -> Home:
        root = Path(tempfile.mkdtemp(prefix="sb-home-")).resolve()
        self.addCleanup(shutil.rmtree, root)
        return Home(root)

    def registered_home(self, *names: str) -> Home:
        """A home whose side-projects folder holds these checkouts, registered by a scan."""
        home = self.make_home()
        for name in names:
            home.make_checkout(f"side-projects/{name}")
        home.sb_ok("repos", "scan", cwd=home.root)
        return home
