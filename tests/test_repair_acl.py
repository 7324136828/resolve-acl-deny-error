"""Unit tests for repair_acl.py.

All tests run inside isolated temporary directories and never access or modify
the user's live Codex home.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import errno
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import repair_acl


class RepairAclTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test-codex-acl-")
        self.addCleanup(self.temp_dir.cleanup)
        self.home = Path(self.temp_dir.name) / "codex_home"
        self.home.mkdir()
        self.sandbox = self.home / ".sandbox"
        self.sandbox.mkdir()
        self.state_file = self.sandbox / repair_acl.STATE_NAME

        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(self.stdout))
        self.stack.enter_context(redirect_stderr(self.stderr))

    def get_backups(self) -> list[Path]:
        return list(self.sandbox.glob(f"{repair_acl.STATE_NAME}.corrupt-*.bak"))

    def test_22_nul_bytes_detected_and_quarantined(self):
        corrupt_data = b"\x00" * 22
        self.state_file.write_bytes(corrupt_data)

        # 1. Check
        check = repair_acl.check_codex_state(self.home)
        self.assertEqual(check.status, repair_acl.StateStatus.CORRUPT)
        self.assertTrue(check.can_repair)
        self.assertIn("22 bytes", check.message)

        # 2. Repair
        repair = repair_acl.repair_codex_state(self.home, check_only=False)
        self.assertTrue(repair.success)
        self.assertEqual(repair.status, repair_acl.StateStatus.HEALTHY)
        self.assertFalse(self.state_file.exists())

        backups = self.get_backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), corrupt_data)
        self.assertEqual(repair.backup_file, backups[0])

    def test_empty_and_malformed_formats_quarantined(self):
        corrupt_samples = [
            b"",
            b"not JSON at all",
            b'{"unclosed": [',
            b"\xff\xfe",
            b'{"val": NaN}',
            b'{"val": Infinity}',
            b"\xef\xbb\xbf{}",  # BOM not accepted by Rust UTF-8 JSON loader
        ]
        for data in corrupt_samples:
            with self.subTest(data=data):
                self.state_file.write_bytes(data)
                check = repair_acl.check_codex_state(self.home)
                self.assertEqual(check.status, repair_acl.StateStatus.CORRUPT)

                repair = repair_acl.repair_codex_state(self.home)
                self.assertTrue(repair.success)
                self.assertFalse(self.state_file.exists())

                backups = self.get_backups()
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), data)
                backups[0].unlink()

    def test_valid_json_is_preserved_and_untouched(self):
        valid_samples = [
            b"{}",
            b'{"version": 1, "paths": ["C:\\\\Users\\\\test"]}',
            b"null",
            b"[1, 2, 3, true]",
            b'  {"text": "\xc3\xa9"}\r\n',
            b'{"future_schema": {"flag": true, "items": []}}',
        ]
        for data in valid_samples:
            with self.subTest(data=data):
                self.state_file.write_bytes(data)
                mtime_before = self.state_file.stat().st_mtime_ns

                check = repair_acl.check_codex_state(self.home)
                self.assertEqual(check.status, repair_acl.StateStatus.HEALTHY)
                self.assertFalse(check.can_repair)

                repair = repair_acl.repair_codex_state(self.home)
                self.assertTrue(repair.success)
                self.assertEqual(self.state_file.read_bytes(), data)
                self.assertEqual(self.state_file.stat().st_mtime_ns, mtime_before)
                self.assertEqual(self.get_backups(), [])

    def test_check_only_mode_does_not_modify_files(self):
        corrupt_data = b"\x00" * 22
        self.state_file.write_bytes(corrupt_data)
        mtime_before = self.state_file.stat().st_mtime_ns

        result = repair_acl.repair_codex_state(self.home, check_only=True)
        self.assertFalse(result.success)
        self.assertEqual(result.status, repair_acl.StateStatus.CORRUPT)
        self.assertTrue(self.state_file.exists())
        self.assertEqual(self.state_file.read_bytes(), corrupt_data)
        self.assertEqual(self.state_file.stat().st_mtime_ns, mtime_before)
        self.assertEqual(self.get_backups(), [])

    def test_missing_state_file(self):
        check = repair_acl.check_codex_state(self.home)
        self.assertEqual(check.status, repair_acl.StateStatus.NOT_FOUND)
        self.assertFalse(check.can_repair)

        repair = repair_acl.repair_codex_state(self.home)
        self.assertTrue(repair.success)
        self.assertFalse(self.state_file.exists())
        self.assertEqual(list(self.sandbox.iterdir()), [])

    def test_missing_sandbox_directory(self):
        self.sandbox.rmdir()
        check = repair_acl.check_codex_state(self.home)
        self.assertEqual(check.status, repair_acl.StateStatus.NOT_FOUND)
        self.assertFalse(self.sandbox.exists())

    def test_idempotency_and_preservation_of_older_backups(self):
        old_bak = self.sandbox / f"{repair_acl.STATE_NAME}.corrupt-20260101-old.bak"
        old_bak.write_bytes(b"prior corrupt backup")

        self.state_file.write_bytes(b"\x00" * 22)
        res1 = repair_acl.repair_codex_state(self.home)
        self.assertTrue(res1.success)

        # Run again - now state file is gone
        res2 = repair_acl.repair_codex_state(self.home)
        self.assertTrue(res2.success)

        # Both the old backup and new backup should still exist
        self.assertTrue(old_bak.exists())
        self.assertEqual(old_bak.read_bytes(), b"prior corrupt backup")
        backups = self.get_backups()
        self.assertEqual(len(backups), 2)

    def test_concurrent_modification_detected_on_repair(self):
        self.state_file.write_bytes(b"\x00" * 22)
        read_snap = repair_acl.read_snapshot
        calls = 0

        def mutate_on_second_read(path):
            nonlocal calls
            calls += 1
            if calls == 2:
                path.write_bytes(b'{"now": "valid"}')
            return read_snap(path)

        with mock.patch.object(repair_acl, "read_snapshot", side_effect=mutate_on_second_read):
            with self.assertRaisesRegex(repair_acl.RepairError, "became valid while diagnosing"):
                repair_acl.repair_codex_state(self.home)

    def test_oversized_file_rejected(self):
        with mock.patch("repair_acl.MAX_STATE_BYTES", 50):
            self.state_file.write_bytes(b"\x00" * 100)
            with self.assertRaisesRegex(repair_acl.RepairError, "exceeds"):
                repair_acl.check_codex_state(self.home)

    def test_cli_json_check(self):
        self.state_file.write_bytes(b"\x00" * 22)
        ret = repair_acl.main(["--codex-home", str(self.home), "--check", "--json", "--force-platform"])
        self.assertEqual(ret, 2)
        out = json.loads(self.stdout.getvalue())
        self.assertEqual(out["status"], "corrupt")
        self.assertTrue(out["check"]["can_repair"])

    def test_cli_fix(self):
        self.state_file.write_bytes(b"\x00" * 22)
        ret = repair_acl.main(["--codex-home", str(self.home), "--fix", "--json", "--force-platform"])
        self.assertEqual(ret, 0)
        out = json.loads(self.stdout.getvalue())
        self.assertTrue(out["success"])
        self.assertIsNotNone(out["backup_file"])
        self.assertFalse(self.state_file.exists())


    def test_access_denied_handled_gracefully(self):
        self.state_file.write_bytes(b"\x00" * 22)
        denied = PermissionError(errno.EACCES, "denied", str(self.state_file))
        with mock.patch.object(repair_acl, "read_snapshot", side_effect=denied):
            ret = repair_acl.main(["--codex-home", str(self.home), "--fix", "--force-platform"])
        self.assertEqual(ret, 1)
        self.assertIn("Access denied", self.stderr.getvalue())

    def create_symlink_or_skip(self, link: Path, target: Path, is_directory: bool = False):
        try:
            link.symlink_to(target, target_is_directory=is_directory)
        except (OSError, NotImplementedError) as err:
            self.skipTest(f"Symlinks not available: {err}")

    def test_state_symlink_refused(self):
        target = Path(self.temp_dir.name) / "external_state.json"
        target.write_bytes(b"\x00" * 22)
        self.create_symlink_or_skip(self.state_file, target)
        with self.assertRaisesRegex(repair_acl.RepairError, "link"):
            repair_acl.check_codex_state(self.home)
        self.assertEqual(target.read_bytes(), b"\x00" * 22)
        self.assertEqual(self.get_backups(), [])

    def test_sandbox_symlink_refused(self):
        target = Path(self.temp_dir.name) / "external_sandbox"
        target.mkdir()
        target_state = target / repair_acl.STATE_NAME
        target_state.write_bytes(b"\x00" * 22)
        self.sandbox.rmdir()
        self.create_symlink_or_skip(self.sandbox, target, is_directory=True)
        with self.assertRaisesRegex(repair_acl.RepairError, "link"):
            repair_acl.check_codex_state(self.home)
        self.assertEqual(target_state.read_bytes(), b"\x00" * 22)
        self.assertEqual(self.get_backups(), [])


if __name__ == "__main__":
    unittest.main()

