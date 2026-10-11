"""Exercise the actual GUI layout and save flow in an isolated Codex home.

Run using xvfb-run on Linux; this is separate from the headless unit suite.
"""

from pathlib import Path
import sys
import tempfile
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codex_config import read_codex_config, update_codex_config
from settings_gui import SettingsDialog
from turtle_gui import CodexRepairUI


def main():
    with tempfile.TemporaryDirectory(prefix="test-codex-gui-") as directory:
        home = Path(directory).resolve() / "codex-home"
        state = home / ".sandbox" / "deny_read_acl_state.json"
        state.parent.mkdir(parents=True)
        state.write_bytes(b"\x00" * 22)
        ui = CodexRepairUI(home)
        parent = ui.screen.getcanvas().winfo_toplevel()
        try:
            messages = []
            with mock.patch("settings_gui.messagebox.showinfo"), mock.patch(
                "settings_gui.messagebox.showerror", side_effect=AssertionError):
                dialog = SettingsDialog(parent, home, messages.append)
                parent.update()
                # The dialog should size itself to show every control, including Save.
                frame = dialog.window.winfo_children()[0]
                assert frame.winfo_height() >= frame.winfo_reqheight()
                dialog.preset.set("Approve for me; workspace write")
                dialog.select_preset()
                dialog.model.set("gpt-6.1-sol")
                parent.update()
                dialog.save()
            assert messages and "Saved" in messages[0]
            settings = read_codex_config(home).settings
            assert settings["approval_policy"] == "on-request"
            assert settings["approvals_reviewer"] == "auto_review"
            assert settings["sandbox_mode"] == "workspace-write"
            assert settings["model"] == "gpt-6.1-sol"
            assert state.read_bytes() == b"\x00" * 22, "Settings triggered an ACL repair"
            # Saving permissions must not restore a stale, untouched model field.
            with mock.patch("settings_gui.messagebox.showinfo"), mock.patch(
                "settings_gui.messagebox.showerror", side_effect=AssertionError):
                dialog = SettingsDialog(parent, home, messages.append)
                update_codex_config(home, model="changed-elsewhere")
                dialog.preset.set("Read only; ask for approval")
                dialog.select_preset()
                dialog.save()
            assert read_codex_config(home).settings["model"] == "changed-elsewhere"
        finally:
            ui.screen.bye()
    print("GUI layout and settings save smoke test passed.")


if __name__ == "__main__":
    main()
