"""Build native GUI and CLI apps, smoke-test them, then archive for a release."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(*command):
    subprocess.run(command, cwd=ROOT, check=True)


def smoke_test(executable):
    # Every path is isolated from the runner's live Codex configuration.
    with tempfile.TemporaryDirectory(prefix="codex-release-test-") as directory:
        home = Path(directory).resolve() / "codex-home"
        subprocess.run([str(executable), "--help"], check=True, stdout=subprocess.PIPE, timeout=60)
        result = subprocess.run([
            str(executable), "--codex-home", str(home), "--config-set",
            "--permission-level", "approve-for-me", "--model", "gpt-6.1-sol", "--json",
        ], check=True, capture_output=True, text=True, timeout=60)
        settings = json.loads(result.stdout)["settings"]
        assert settings == {
            "approval_policy": "on-request", "approvals_reviewer": "auto_review",
            "sandbox_mode": "workspace-write", "model": "gpt-6.1-sol",
        }, settings
        subprocess.run([str(executable), "--codex-home", str(home), "--config-show", "--json"],
                       check=True, stdout=subprocess.PIPE, timeout=60)
        state = home / ".sandbox" / "deny_read_acl_state.json"
        state.parent.mkdir()
        state.write_bytes(b"\x00" * 22)
        command = [str(executable), "--codex-home", str(home), "--check", "--json", "--force-platform"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        assert result.returncode == 2, result.stderr
        assert json.loads(result.stdout)["status"] == "corrupt"
        command[command.index("--check")] = "--fix"
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
        backup = Path(json.loads(result.stdout)["backup_file"])
        assert backup.read_bytes() == b"\x00" * 22


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=(
        "windows-x64", "ubuntu-x64", "macos-arm64", "macos-x64",
    ))
    args = parser.parse_args()
    expected_os = args.target.split("-")[0]
    actual_os = {"win32": "windows", "linux": "ubuntu", "darwin": "macos"}.get(sys.platform)
    if actual_os != expected_os:
        parser.error("Build each target on its native operating system.")
    expected_arch = "arm64" if args.target.endswith("arm64") else "x64"
    actual_arch = {"arm64": "arm64", "aarch64": "arm64", "amd64": "x64", "x86_64": "x64"}.get(
        platform.machine().lower())
    if actual_arch != expected_arch:
        parser.error(f"Target needs {expected_arch}, but Python is running on {actual_arch}.")

    for name, gui in (("codex-repair", True), ("codex-repair-cli", False)):
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
                   "--name", name, "--distpath", str(ROOT / "dist"),
                   "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
                   "--hidden-import", "turtle_gui", "--hidden-import", "settings_gui"]
        if gui and sys.platform != "linux":
            command.append("--windowed")
        command.append(str(ROOT / "repair_acl.py"))
        run(*command)

    suffix = ".exe" if sys.platform == "win32" else ""
    smoke_test(ROOT / "dist" / "codex-repair-cli" / ("codex-repair-cli" + suffix))
    # Tk's data files must be bundled even though a headless CLI smoke test doesn't use them.
    assert list((ROOT / "dist" / "codex-repair").rglob("init.tcl")), "Tk runtime was not bundled"

    output = ROOT / "dist" / "release"
    output.mkdir(exist_ok=True)
    # Staging directories are unique; do not recursively delete any existing build.
    with tempfile.TemporaryDirectory(prefix="release-", dir=ROOT / "build") as directory:
        stage = Path(directory)
        if sys.platform == "darwin":
            shutil.copytree(ROOT / "dist" / "codex-repair.app", stage / "Codex Repair.app", symlinks=True)
        else:
            shutil.copytree(ROOT / "dist" / "codex-repair", stage / "codex-repair", symlinks=True)
        shutil.copytree(ROOT / "dist" / "codex-repair-cli", stage / "codex-repair-cli", symlinks=True)
        for filename in ("README.md", "LICENSE"):
            shutil.copy2(ROOT / filename, stage / filename)
        archive = Path(shutil.make_archive(
            str(output / f"codex-repair-{args.target}"),
            "zip" if sys.platform == "win32" else "gztar", root_dir=stage,
        ))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + ".sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Release archive: {archive}")


if __name__ == "__main__":
    main()
