"""`sb repos scan` registers every git checkout directly under the side-projects folder."""

import unittest

from tests.sb_harness import SbTestCase


class RepoScanTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.make_home()
        self.home.make_checkout("side-projects/alpha")
        self.home.make_checkout("side-projects/beta")
        (self.home.side_projects / "notes").mkdir()
        (self.home.side_projects / "readme.txt").write_text("not a checkout\n")
        self.home.make_checkout("side-projects/group/inner")

    def test_scan_registers_each_checkout_directly_under_side_projects(self) -> None:
        result = self.home.sb("repos", "scan", cwd=self.home.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT COUNT(*) FROM repos"), [(2,)])

    def test_scan_names_each_repo_after_its_directory(self) -> None:
        result = self.home.sb("repos", "scan", cwd=self.home.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.home.rows("SELECT name FROM repos ORDER BY name"), [("alpha",), ("beta",)]
        )

    def test_second_scan_adds_nothing(self) -> None:
        self.home.sb_ok("repos", "scan", cwd=self.home.root)
        first = self.home.rows("SELECT id, name, path FROM repos ORDER BY id")

        result = self.home.sb("repos", "scan", cwd=self.home.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT id, name, path FROM repos ORDER BY id"), first)

    def test_scan_after_a_new_checkout_registers_it(self) -> None:
        self.home.sb_ok("repos", "scan", cwd=self.home.root)
        self.home.make_checkout("side-projects/gamma")

        result = self.home.sb("repos", "scan", cwd=self.home.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT COUNT(*) FROM repos"), [(3,)])


class EmptySideProjectsTest(SbTestCase):
    def setUp(self) -> None:
        self.home = self.make_home()

    def test_scan_of_an_empty_side_projects_folder_registers_nothing(self) -> None:
        result = self.home.sb("repos", "scan", cwd=self.home.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT COUNT(*) FROM repos"), [(0,)])

    def test_scan_registers_a_checkout_whose_name_has_spaces_and_accents(self) -> None:
        self.home.make_checkout("side-projects/café notes")

        result = self.home.sb("repos", "scan", cwd=self.home.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT name FROM repos"), [("café notes",)])


if __name__ == "__main__":
    unittest.main()
