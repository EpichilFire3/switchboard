"""The switchboard database is SQLite in WAL mode with a versioned schema, migrated forward to the
current version when any `sb` command starts."""

import contextlib
import sqlite3
import unittest

from tests.sb_harness import SbTestCase

CURRENT_SCHEMA_VERSION = 1
RUN_COMMAND_RECORDS = {"repos", "runs", "tickets", "decisions"}


class SchemaMigrationTest(SbTestCase):
    """A database file already exists at schema version 0, older than current."""

    def setUp(self) -> None:
        self.home = self.make_home()
        self.repo = self.home.make_checkout("side-projects/alpha")
        self.home.db_path.parent.mkdir()
        self.home.db_path.touch()
        with contextlib.closing(sqlite3.connect(self.home.db_path)) as conn:
            conn.execute("PRAGMA user_version = 0")
            conn.commit()

    def test_command_migrates_a_version_zero_database_to_the_current_version(self) -> None:
        result = self.home.sb("repos", "scan", cwd=self.home.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.pragma("user_version"), CURRENT_SCHEMA_VERSION)

    def test_migrated_database_holds_the_run_command_records(self) -> None:
        result = self.home.sb("repos", "scan", cwd=self.home.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLessEqual(RUN_COMMAND_RECORDS, self.home.table_names())

    def test_migrated_database_records_the_scan(self) -> None:
        result = self.home.sb("repos", "scan", cwd=self.home.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.home.rows("SELECT COUNT(*) FROM repos"), [(1,)])

    def test_run_command_migrates_a_version_zero_database(self) -> None:
        self.home.sb("status", "progress", cwd=self.repo, env={"SB_RUN_ID": "r1", "SB_TICKET": "5"})

        self.assertEqual(self.home.pragma("user_version"), CURRENT_SCHEMA_VERSION)


class JournalModeTest(SbTestCase):
    def test_database_is_in_wal_mode(self) -> None:
        home = self.make_home()
        home.make_checkout("side-projects/alpha")

        result = home.sb("repos", "scan", cwd=home.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(home.pragma("journal_mode"), "wal")


if __name__ == "__main__":
    unittest.main()
