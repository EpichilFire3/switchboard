"""A run command resolves its repo from the git common directory of the current directory, so an
epf3 worktree resolves to its parent repo; an unregistered repo exits non-zero naming
`sb repos scan`."""

import unittest

from tests.sb_harness import Home, SbTestCase

WORKTREE_LOCATIONS = (
    ("implement-tests worktree", ".worktrees/feat-1"),
    ("claude agent worktree", ".claude/worktrees/agent-1"),
)

TICKETS_IN_BETA = (
    "SELECT number FROM tickets"
    " WHERE repo_id = (SELECT repo_id FROM tickets WHERE number = 2) ORDER BY number"
)


def checkout_outside_side_projects(home: Home):
    return home.make_checkout("elsewhere/gamma")


def checkout_added_after_the_scan(home: Home):
    return home.make_checkout("side-projects/delta")


def directory_outside_any_checkout(home: Home):
    path = home.root / "plain"
    path.mkdir()
    return path


UNREGISTERED_CASES = (
    ("status from a checkout outside side-projects", checkout_outside_side_projects, ("status", "progress")),
    ("status from a checkout added after the scan", checkout_added_after_the_scan, ("status", "progress")),
    ("status from a directory outside any checkout", directory_outside_any_checkout, ("status", "progress")),
    ("decide from a checkout outside side-projects", checkout_outside_side_projects, ("decide", "x")),
)

RUN_ON_TICKET_5 = {"SB_RUN_ID": "r1", "SB_TICKET": "5"}
RUN_WITHOUT_TICKET = {"SB_RUN_ID": "r1"}

TICKET_REPOS = (
    "SELECT repos.name, tickets.number FROM tickets JOIN repos ON repos.id = tickets.repo_id"
)
DECISION_REPOS = (
    "SELECT repos.name, decisions.text FROM decisions JOIN repos ON repos.id = decisions.repo_id"
)


def registered_checkout_alpha(home: Home):
    return home.side_projects / "alpha"


SB_REPO_CWDS = (
    ("from another registered checkout", registered_checkout_alpha),
    ("from a directory outside any checkout", directory_outside_any_checkout),
    ("from a checkout outside side-projects", checkout_outside_side_projects),
)

# (case, SB_REPO value, command). Every case also has an unregistered checkout `delta` on disk
# under side-projects, and runs from the registered checkout `alpha`.
SB_REPO_UNREGISTERED_CASES = (
    ("status with an unknown name", "nosuch", ("status", "progress")),
    ("decide with an unknown name", "nosuch", ("decide", "x")),
    ("status naming a checkout added after the scan", "delta", ("status", "progress")),
)

TICKETLESS_UNREGISTERED_CASES = (
    ("decide from a directory outside any checkout", directory_outside_any_checkout, ("decide", "x")),
    ("decide from a checkout outside side-projects", checkout_outside_side_projects, ("decide", "x")),
    ("status from a directory outside any checkout", directory_outside_any_checkout, ("status", "done")),
    ("status from a checkout outside side-projects", checkout_outside_side_projects, ("status", "done")),
)


class WorktreeResolutionTest(SbTestCase):
    def test_worktree_resolves_to_its_parent_repo(self) -> None:
        for case, location in WORKTREE_LOCATIONS:
            with self.subTest(case):
                home = self.make_home()
                alpha = home.make_checkout("side-projects/alpha")
                beta = home.make_checkout("side-projects/beta")
                worktree = home.add_worktree(beta, location)
                home.sb_ok("repos", "scan", cwd=home.root)
                home.sb_ok("status", "progress", cwd=alpha, env={"SB_RUN_ID": "r1", "SB_TICKET": "1"})
                home.sb_ok("status", "progress", cwd=beta, env={"SB_RUN_ID": "r1", "SB_TICKET": "2"})

                result = home.sb("status", "progress", cwd=worktree, env={"SB_RUN_ID": "r1", "SB_TICKET": "3"})

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(home.rows(TICKETS_IN_BETA), [(2,), (3,)])

    def test_subdirectory_of_a_checkout_resolves_to_that_repo(self) -> None:
        home = self.registered_home("alpha", "beta")
        alpha = home.side_projects / "alpha"
        beta = home.side_projects / "beta"
        nested = beta / "docs" / "deep"
        nested.mkdir(parents=True)
        home.sb_ok("status", "progress", cwd=alpha, env={"SB_RUN_ID": "r1", "SB_TICKET": "1"})
        home.sb_ok("status", "progress", cwd=beta, env={"SB_RUN_ID": "r1", "SB_TICKET": "2"})

        result = home.sb("status", "progress", cwd=nested, env={"SB_RUN_ID": "r1", "SB_TICKET": "3"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(home.rows(TICKETS_IN_BETA), [(2,), (3,)])

    def test_same_ticket_number_in_two_repos_gets_two_records(self) -> None:
        home = self.registered_home("alpha", "beta")
        home.sb_ok("status", "progress", cwd=home.side_projects / "alpha", env=RUN_ON_TICKET_5)

        result = home.sb("status", "progress", cwd=home.side_projects / "beta", env=RUN_ON_TICKET_5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            home.rows("SELECT COUNT(DISTINCT repo_id) FROM tickets WHERE number = 5"), [(2,)]
        )


class UnregisteredRepoTest(SbTestCase):
    def test_unregistered_repo_exits_non_zero_naming_repos_scan(self) -> None:
        for case, make_cwd, args in UNREGISTERED_CASES:
            with self.subTest(case):
                home = self.registered_home("alpha")
                cwd = make_cwd(home)

                result = home.sb(*args, cwd=cwd, env=RUN_ON_TICKET_5)

                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn("sb repos scan", result.stderr)

    def test_unregistered_repo_creates_no_ticket_record(self) -> None:
        for case, make_cwd, args in UNREGISTERED_CASES:
            with self.subTest(case):
                home = self.registered_home("alpha")
                cwd = make_cwd(home)

                home.sb(*args, cwd=cwd, env=RUN_ON_TICKET_5)

                self.assertEqual(home.rows("SELECT number FROM tickets"), [])

    def test_command_before_any_scan_exits_non_zero_naming_repos_scan(self) -> None:
        home = self.make_home()
        repo = home.make_checkout("side-projects/alpha")

        result = home.sb("status", "progress", cwd=repo, env=RUN_ON_TICKET_5)

        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("sb repos scan", result.stderr)


class TicketlessUnregisteredRepoTest(SbTestCase):
    """A run command with no ticket still resolves its repo, so an unregistered one fails it."""

    def test_ticketless_command_from_an_unregistered_directory_exits_non_zero_naming_repos_scan(
        self,
    ) -> None:
        for case, make_cwd, args in TICKETLESS_UNREGISTERED_CASES:
            with self.subTest(case):
                home = self.registered_home("alpha")
                cwd = make_cwd(home)

                result = home.sb(*args, cwd=cwd, env=RUN_WITHOUT_TICKET)

                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn("sb repos scan", result.stderr)

    def test_ticketless_command_from_an_unregistered_directory_writes_nothing(self) -> None:
        for case, make_cwd, args in TICKETLESS_UNREGISTERED_CASES:
            with self.subTest(case):
                home = self.registered_home("alpha")
                cwd = make_cwd(home)
                before = home.contents()

                home.sb(*args, cwd=cwd, env=RUN_WITHOUT_TICKET)

                self.assertEqual(home.contents(), before)


class SbRepoResolutionTest(SbTestCase):
    """`SB_REPO`, when set, is the repo, whatever the current directory."""

    def test_sb_repo_names_the_repo_from_any_directory(self) -> None:
        for case, make_cwd in SB_REPO_CWDS:
            with self.subTest(case):
                home = self.registered_home("alpha", "beta")
                cwd = make_cwd(home)

                result = home.sb(
                    "status", "progress", cwd=cwd, env={**RUN_ON_TICKET_5, "SB_REPO": "beta"}
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(home.rows(TICKET_REPOS), [("beta", 5)])

    def test_sb_repo_names_the_repo_a_ticketless_decision_records(self) -> None:
        home = self.registered_home("alpha", "beta")

        result = home.sb(
            "decide", "x",
            cwd=home.side_projects / "alpha", env={**RUN_WITHOUT_TICKET, "SB_REPO": "beta"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(home.rows(DECISION_REPOS), [("beta", "x")])

    def test_sb_repo_naming_no_registered_repo_exits_non_zero_naming_repos_scan(self) -> None:
        for case, value, args in SB_REPO_UNREGISTERED_CASES:
            with self.subTest(case):
                home = self.registered_home("alpha")
                home.make_checkout("side-projects/delta")

                result = home.sb(
                    *args, cwd=home.side_projects / "alpha", env={**RUN_ON_TICKET_5, "SB_REPO": value}
                )

                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn("sb repos scan", result.stderr)

    def test_sb_repo_naming_no_registered_repo_writes_nothing(self) -> None:
        for case, value, args in SB_REPO_UNREGISTERED_CASES:
            with self.subTest(case):
                home = self.registered_home("alpha")
                home.make_checkout("side-projects/delta")
                before = home.contents()

                home.sb(
                    *args, cwd=home.side_projects / "alpha", env={**RUN_ON_TICKET_5, "SB_REPO": value}
                )

                self.assertEqual(home.contents(), before)


if __name__ == "__main__":
    unittest.main()
