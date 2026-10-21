"""Money-preserving migration and concurrent admission regression tests."""
import concurrent.futures
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spotify_pipeline import storage
from spotify_pipeline.storage import BudgetExceeded, BudgetLedger


class ProviderAdmissionIndexTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "spend.sqlite3"

    def tearDown(self):
        self.directory.cleanup()

    def legacy(self):
        c = sqlite3.connect(self.path)
        c.executescript("""
          CREATE TABLE spend(request_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,
            reserved_nano INTEGER NOT NULL CHECK(reserved_nano>=0),charged_nano INTEGER,
            state TEXT NOT NULL,created_at TEXT NOT NULL,settled_at TEXT);
          CREATE TABLE spend_provider(request_id TEXT PRIMARY KEY,provider TEXT NOT NULL);
        """)
        rows = [("unknown", "old", 2_000_000_000, None, "unknown", "t0", "t1"),
                ("known", "old", 5_000_000_000, 3_000_000_000, "settled", "t0", "t1"),
                ("reserved", "other", 4_000_000_000, None, "reserved", "t0", None),
                ("free", "other", 1_000_000_000, 0, "settled", "t0", "t1")]
        c.executemany("INSERT INTO spend VALUES(?,?,?,?,?,?,?)", rows)
        c.executemany("INSERT INTO spend_provider VALUES(?,?)", [("known", "a"), ("reserved", "b"), ("free", "a")])
        c.commit(); c.close()
        return rows

    def assert_provider_equivalence(self, ledger):
        for provider in ("a", "b", "unknown-provider"):
            expected = ledger.conn.execute("""SELECT COALESCE(SUM(COALESCE(s.charged_nano,s.reserved_nano)),0)
              FROM spend s LEFT JOIN spend_provider p ON s.request_id=p.request_id
              WHERE p.provider=? OR p.provider IS NULL""", (provider,)).fetchone()[0]
            actual = ledger.conn.execute("""SELECT
              (SELECT COALESCE(SUM(COALESCE(charged_nano,reserved_nano)),0) FROM spend WHERE admission_provider=?) +
              (SELECT COALESCE(SUM(COALESCE(charged_nano,reserved_nano)),0) FROM spend WHERE admission_provider IS NULL)
              """, (provider,)).fetchone()[0]
            self.assertEqual(expected, actual)

    def test_migration_preserves_original_columns_and_all_amounts(self):
        rows = self.legacy()
        ledger = BudgetLedger(self.path)
        after = [tuple(row) for row in ledger.conn.execute("""SELECT request_id,run_id,reserved_nano,charged_nano,
          state,created_at,settled_at FROM spend ORDER BY request_id""")]
        self.assertEqual(sorted(rows), after)
        self.assertEqual(ledger.totals()["committed_usd"], 9)
        self.assert_provider_equivalence(ledger)
        ledger.close()
        reopened = BudgetLedger(self.path)
        self.assertEqual(reopened.totals()["committed_usd"], 9)
        self.assert_provider_equivalence(reopened)
        reopened.close()

    def test_unknown_untagged_counts_against_every_provider_and_exact_cap(self):
        self.legacy(); ledger = BudgetLedger(self.path)
        ledger.reserve("at-cap", "new", 5, global_cap_usd=100, run_cap_usd=100, provider="a", provider_cap_usd=10)
        with self.assertRaises(BudgetExceeded):
            ledger.reserve("over-cap", "new", 0.000000001, global_cap_usd=100, run_cap_usd=100, provider="a", provider_cap_usd=10)
        self.assertIsNone(ledger.conn.execute("SELECT 1 FROM spend WHERE request_id='over-cap'").fetchone())
        ledger.settle("at-cap", 1)
        ledger.reserve("released-cap", "new", 4, global_cap_usd=100, run_cap_usd=100, provider="a", provider_cap_usd=10)
        ledger.settle("released-cap", None)
        self.assert_provider_equivalence(ledger)
        self.assertEqual(ledger.totals()["unknown_charge_hold_usd"], 6)
        ledger.close()

    def test_triggers_follow_tag_insert_update_delete_and_prior_orphan(self):
        self.legacy(); ledger = BudgetLedger(self.path)
        ledger.conn.execute("INSERT INTO spend_provider VALUES('unknown','a')")
        self.assert_provider_equivalence(ledger)
        ledger.conn.execute("UPDATE spend_provider SET provider='b' WHERE request_id='unknown'")
        self.assert_provider_equivalence(ledger)
        ledger.conn.execute("UPDATE spend_provider SET request_id='orphan' WHERE request_id='unknown'")
        self.assert_provider_equivalence(ledger)
        ledger.reserve("orphan", "new", 1, global_cap_usd=100, run_cap_usd=100)
        self.assert_provider_equivalence(ledger)
        ledger.conn.execute("DELETE FROM spend_provider WHERE request_id='orphan'")
        self.assert_provider_equivalence(ledger)
        ledger.close()

    def test_two_connections_cannot_over_admit_provider_cap(self):
        BudgetLedger(self.path).close()
        def reserve_many(prefix):
            ledger = BudgetLedger(self.path); succeeded = 0
            try:
                for i in range(10):
                    try:
                        ledger.reserve(f"{prefix}-{i}", prefix, 1, global_cap_usd=100, run_cap_usd=100, provider="a", provider_cap_usd=15)
                        succeeded += 1
                    except BudgetExceeded:
                        pass
                return succeeded
            finally:
                ledger.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            counts = list(pool.map(reserve_many, ("one", "two")))
        self.assertEqual(sum(counts), 15)
        ledger = BudgetLedger(self.path)
        self.assertEqual(ledger.totals()["reserved_usd"], 15)
        self.assert_provider_equivalence(ledger)
        ledger.close()

    def test_inconsistent_existing_cache_fails_closed(self):
        self.legacy(); ledger = BudgetLedger(self.path)
        ledger.conn.execute("UPDATE spend SET admission_provider='wrong' WHERE request_id='known'")
        ledger.close()
        with self.assertRaisesRegex(RuntimeError, "disagrees"):
            BudgetLedger(self.path)

    def test_migration_failure_rolls_back_added_column(self):
        self.legacy()
        conn = storage._connect(self.path)
        def authorize(action, arg1, arg2, db, trigger):
            return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_INDEX and arg1 == 'spend_commitment_cover_v1' else sqlite3.SQLITE_OK
        conn.set_authorizer(authorize)
        with patch.object(storage, "_connect", return_value=conn):
            with self.assertRaises(sqlite3.DatabaseError):
                BudgetLedger(self.path)
        conn.set_authorizer(None)
        self.assertNotIn("admission_provider", [r[1] for r in conn.execute("PRAGMA table_info(spend)")])
        conn.close()


if __name__ == "__main__":
    unittest.main()
