"""Config edits use isolated homes and never read the user's live defaults."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

import codex_config
import repair_acl
import tomlkit


class CodexConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="test-codex-config-")
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name).resolve() / "codex-home"
        self.home.mkdir()
        self.path = self.home / "config.toml"

    def backups(self):
        return list(self.home.glob("config.toml.backup-*.bak"))

    def test_approve_for_me_and_custom_model_create_missing_home(self):
        self.home.rmdir()
        result = codex_config.update_codex_config(
            self.home, permission_level="approve-for-me", model="gpt-6.1-sol")
        self.assertTrue(result.changed)
        self.assertIsNone(result.backup_file)
        self.assertEqual(tomlkit.parse(self.path.read_text()), {
            "approval_policy": "on-request", "approvals_reviewer": "auto_review",
            "sandbox_mode": "workspace-write", "model": "gpt-6.1-sol",
        })

    def test_preserves_comments_tables_and_exact_backup_bytes(self):
        original = (
            '# My defaults\r\nmodel = "old" # keep this comment\r\n'
            '[sandbox_workspace_write]\r\nnetwork_access = true\r\n'
            '[mcp_servers.example]\r\ncommand = "example"\r\n'
            '[projects."C:\\repo"]\r\ntrust_level = "trusted"\r\n'
        ).encode()
        # TOML quoted Windows paths need literal strings or escaped backslashes.
        original = original.replace(b'[projects."C:\\repo"]', b"[projects.'C:\\repo']")
        self.path.write_bytes(original)
        result = codex_config.update_codex_config(self.home, permission_level="workspace", model="my-custom-model")
        self.assertEqual(result.backup_file.read_bytes(), original)
        updated = self.path.read_bytes().decode()
        self.assertIn("# My defaults", updated)
        self.assertIn('# keep this comment', updated)
        document = tomlkit.parse(updated)
        self.assertTrue(document["sandbox_workspace_write"]["network_access"])
        self.assertEqual(document["mcp_servers"]["example"]["command"], "example")
        self.assertEqual(document["projects"]["C:\\repo"]["trust_level"], "trusted")
        self.assertEqual(document["model"], "my-custom-model")
        self.assertEqual(document["sandbox_mode"], "workspace-write")

    def test_model_only_preserves_granular_policy_and_permissions_profile(self):
        self.path.write_text(
            'default_permissions = ":workspace"\n'
            'approval_policy = { granular = { sandbox_approval = false, rules = true } }\n', encoding="utf-8")
        codex_config.update_codex_config(self.home, model="custom")
        document = tomlkit.parse(self.path.read_text())
        self.assertEqual(document["default_permissions"], ":workspace")
        self.assertFalse(document["approval_policy"]["granular"]["sandbox_approval"])
        self.assertNotIn("sandbox_mode", document)

    def test_presets_and_individual_settings(self):
        for level, expected in codex_config.PERMISSION_LEVELS.items():
            with self.subTest(level=level):
                result = codex_config.update_codex_config(self.home, permission_level=level)
                self.assertEqual(tuple(result.settings[key] for key in (
                    "approval_policy", "approvals_reviewer", "sandbox_mode")), expected)
        codex_config.update_codex_config(self.home, approval_policy="on-request", approvals_reviewer="auto_review")
        self.assertEqual(codex_config.read_codex_config(self.home).settings["approvals_reviewer"], "auto_review")

    def test_invalid_inputs_do_not_create_files(self):
        for options in (
            {}, {"permission_level": "invalid"}, {"approval_policy": "untrusted"},
            {"approval_policy": "on-failure"}, {"sandbox_mode": "anything"},
            {"approvals_reviewer": "anything"}, {"model": " "}, {"model": "a\nb"},
            {"permission_level": "workspace", "approval_policy": "never"},
        ):
            with self.subTest(options=options), self.assertRaises(codex_config.ConfigError):
                codex_config.update_codex_config(self.home, **options)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_invalid_toml_and_utf8_remain_untouched(self):
        for raw in (b'broken = [', b"\xff", b'model = "a"\nmodel = "b"\n'):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                with self.assertRaises(codex_config.ConfigError):
                    codex_config.update_codex_config(self.home, model="new")
                self.assertEqual(self.path.read_bytes(), raw)
                self.assertEqual(self.backups(), [])

    def test_idempotent_save_does_not_create_extra_backups(self):
        self.path.write_text('model = "old"\n')
        codex_config.update_codex_config(self.home, model="new")
        before = self.path.stat().st_mtime_ns
        result = codex_config.update_codex_config(self.home, model="new")
        self.assertFalse(result.changed)
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_profile_conflict_is_reported_without_changes(self):
        original = b'default_permissions = ":workspace"\n'
        self.path.write_bytes(original)
        with self.assertRaisesRegex(codex_config.ConfigError, "default_permissions"):
            codex_config.update_codex_config(self.home, permission_level="approve-for-me")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.backups(), [])

    def test_concurrent_write_is_not_overwritten(self):
        self.path.write_text('model = "old"\n')
        snapshot = codex_config._snapshot
        calls = 0

        def change_on_second_snapshot(path):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.path.write_text('model = "changed-elsewhere"\n')
            return snapshot(path)

        with mock.patch.object(codex_config, "_snapshot", side_effect=change_on_second_snapshot):
            with self.assertRaisesRegex(codex_config.ConfigError, "changed before saving"):
                codex_config.update_codex_config(self.home, model="new")
        self.assertIn("changed-elsewhere", self.path.read_text())
        self.assertEqual(list(self.home.glob(".config-*.tmp")), [])
        self.assertEqual(self.backups(), [])

    def test_replace_failure_keeps_original_and_backup(self):
        self.path.write_bytes(b'model = "old"\n')
        with mock.patch.object(codex_config.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                codex_config.update_codex_config(self.home, model="new")
        self.assertEqual(self.path.read_bytes(), b'model = "old"\n')
        self.assertEqual(self.backups()[0].read_bytes(), b'model = "old"\n')
        self.assertEqual(list(self.home.glob(".config-*.tmp")), [])

    @unittest.skipIf(os.name == "nt", "POSIX file mode test")
    def test_posix_permissions_preserved(self):
        self.path.write_text('model = "old"\n')
        self.path.chmod(0o600)
        result = codex_config.update_codex_config(self.home, model="new")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(result.backup_file.stat().st_mode), 0o600)

    def test_links_are_refused(self):
        target = self.home / "other.toml"
        target.write_bytes(b'model = "old"\n')
        try:
            self.path.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlinks unavailable: {exc}")
        with self.assertRaisesRegex(codex_config.ConfigError, "link"):
            codex_config.update_codex_config(self.home, model="new")
        self.assertEqual(target.read_bytes(), b'model = "old"\n')

    def test_read_missing_config_is_non_destructive(self):
        self.home.rmdir()
        self.assertEqual(codex_config.read_codex_config(self.home).settings, {})
        self.assertFalse(self.home.exists())

    def test_oversized_config_and_update_are_refused(self):
        self.path.write_bytes(b'model = "old"\n' + b'#' * 100)
        original = self.path.read_bytes()
        with mock.patch.object(codex_config, "MAX_CONFIG_BYTES", 50):
            with self.assertRaisesRegex(codex_config.ConfigError, "exceeds"):
                codex_config.update_codex_config(self.home, model="new")
        self.assertEqual(self.path.read_bytes(), original)
        self.path.unlink()
        with mock.patch.object(codex_config, "MAX_CONFIG_BYTES", 50):
            with self.assertRaisesRegex(codex_config.ConfigError, "would exceed"):
                codex_config.update_codex_config(self.home, model="a" * 100)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_cli_config_modes_work_on_non_windows_and_redact_unrelated_data(self):
        self.path.write_text('[model_providers.private]\napi_key = "test-only-secret"\n')
        for mode in ("--config-set", "--config-show"):
            output = io.StringIO()
            args = ["--codex-home", str(self.home), mode, "--json"]
            if mode == "--config-set":
                args += ["--permission-level", "approve-for-me", "--model", "gpt-6.1-sol"]
            with redirect_stdout(output), mock.patch.object(repair_acl, "os", wraps=os) as fake_os:
                fake_os.name = "posix"
                self.assertEqual(repair_acl.main(args), 0)
            self.assertEqual(json.loads(output.getvalue())["settings"]["model"], "gpt-6.1-sol")
            self.assertNotIn("test-only-secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
