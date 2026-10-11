# Codex Repair and Settings

A utility to diagnose and repair the `helper_unknown_error: apply deny-read ACLs` error in OpenAI Codex and ChatGPT on Windows, and edit Codex permission and model defaults on Windows, Ubuntu, and macOS.

## Download an executable

Download your platform's archive from [GitHub Releases](https://github.com/7324136828/resolve-acl-deny-error/releases), then extract the whole archive. Python and pip are bundled; you do not need to install them. Keep each executable beside its `_internal` folder.

| Release asset | Platform | GUI launcher | CLI launcher |
| --- | --- | --- | --- |
| `codex-repair-windows-x64.zip` | Windows x64 | `codex-repair/codex-repair.exe` | `codex-repair-cli/codex-repair-cli.exe` |
| `codex-repair-ubuntu-x64.tar.gz` | Ubuntu 22.04+ x64 | `codex-repair/codex-repair` | `codex-repair-cli/codex-repair-cli` |
| `codex-repair-macos-arm64.tar.gz` | Apple Silicon MacBook/macOS 15+ | `Codex Repair.app` | `codex-repair-cli/codex-repair-cli` |
| `codex-repair-macos-x64.tar.gz` | Intel MacBook/macOS 15+ | `Codex Repair.app` | `codex-repair-cli/codex-repair-cli` |

The GUI opens when launched without arguments. Ubuntu needs a desktop display. macOS builds use ad-hoc signing and are not notarized; Windows builds are not publisher-signed. Your OS may request confirmation to open a downloaded app. A `.sha256` file accompanies each archive.

## Choose Codex permissions and a default model

Open **Settings** in the GUI, choose a permission level or **Custom settings**, enter a model ID such as `gpt-6.1-sol`, and click **Save settings**. The dialog displays the current values and starts with **Keep current permissions**. Leaving the model blank keeps the existing model.

The editor targets `%USERPROFILE%\.codex\config.toml` on Windows and `~/.codex/config.toml` on Ubuntu/macOS. It honors `CODEX_HOME` and `--codex-home`. It preserves unrelated settings and comments, creates a unique `config.toml.backup-<timestamp>-<id>.bak` before changing an existing file, and uses a staged replacement. Identical settings require no write or backup. It refuses malformed TOML, links/reparse points, oversized files, and detected concurrent changes. POSIX file modes are preserved.

| Permission level | `approval_policy` | `approvals_reviewer` | `sandbox_mode` | Effect |
| --- | --- | --- | --- | --- |
| Read only | `on-request` | `user` | `read-only` | Read-only sandbox; Codex can ask to perform actions outside it. |
| Workspace write | `on-request` | `user` | `workspace-write` | Workspace writes; asks you when approval is required. |
| Approve for me | `on-request` | `auto_review` | `workspace-write` | Workspace sandbox; eligible approval requests go to automatic review. |
| Workspace write, no prompts | `never` | `user` | `workspace-write` | Keeps the sandbox; rejects actions that require approval. |
| Full access, no prompts | `never` | `user` | `danger-full-access` | Removes sandbox restrictions and approval prompts. |

The **Approve for me** preset writes the requested defaults:

```toml
approval_policy = "on-request"
approvals_reviewer = "auto_review"
sandbox_mode = "workspace-write"
model = "gpt-6.1-sol"
```

These choices follow the [official OpenAI configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) and [auto-review documentation](https://learn.chatgpt.com/docs/sandboxing/auto-review). `untrusted` is unsupported and `on-failure` is deprecated, so they are not offered. Existing granular approval policies are preserved during model-only edits. If a config uses `default_permissions`, the editor refuses to add the conflicting `sandbox_mode`; use Codex's permission profile controls for that configuration.

Restart Codex after saving. Project overrides, selected configuration profiles, command-line flags, and managed organization policies may take precedence over user defaults. Use a model available to your account; the editor accepts your model ID without making a network request. See [OpenAI's configuration basics](https://learn.chatgpt.com/docs/config-file/config-basic) for precedence and model availability.

CLI examples (replace `python repair_acl.py` with your packaged CLI launcher if using a release):

```powershell
python repair_acl.py --config-show --json
python repair_acl.py --config-set --permission-level approve-for-me --model "gpt-6.1-sol"
python repair_acl.py --config-set --approval-policy on-request --approvals-reviewer user --sandbox-mode read-only
python repair_acl.py --config-set --model "my-model-id"
```

Permission/model options require `--config-set`. Choose either a preset or individual permission fields. Reading defaults never creates a config file; saving creates one if needed. Output contains only the edited permission/model fields.

---

## The Problem

On Windows, Codex uses `%USERPROFILE%\.codex\.sandbox\deny_read_acl_state.json` to track deny-read ACL state across sandbox sessions. When this file becomes corrupted (such as containing only NUL bytes or truncated UTF-8 data after an unexpected shutdown or crash), Codex fails to parse the tracking JSON during startup and crashes with an ACL error.

This tool safely detects corruption in the state file and quarantines it to a timestamped backup (`.corrupt-<timestamp>-<id>.bak`), allowing Codex to cleanly regenerate its tracking state on next launch.

---

## Key Features & Safety Guarantees

- **Python 3.9+**: ACL repair uses the standard library. The settings editor uses `tomlkit` to preserve TOML formatting and comments. Release downloads bundle dependencies.
- **Interactive Turtle GUI**: Clean, modern dark-theme graphical interface with visual inspection, dry-run checking, one-click repair, and quick sandbox folder access.
- **Non-Destructive & Safe by Design**:
  - Never touches or alters valid, parseable JSON files (even with unknown future schemas).
  - Preserves original bytes and Windows file permissions in unique timestamped backups.
  - ACL repair never modifies Windows user privileges, system ACLs, or sandbox security modes. The separate settings editor changes only the defaults you select.
  - Refuses symbolic links, junctions, and reparse points to prevent directory traversal.
  - Detects concurrent modifications between inspection and quarantine.
- **Automation Ready**: First-class CLI with `--check` (dry run), `--fix`, and `--json` machine-readable output.

---

## Quick Start

### 1. Launch Interactive GUI (Recommended)

When running from source, install the settings dependency first:

```powershell
python -m pip install -r requirements.txt
```

Source installations also need Tk support (on Ubuntu: `sudo apt install python3-tk`).

Double-click **`run.bat`** in the repository root, or run:

```powershell
.\run.bat
```

or via Python directly:

```powershell
python repair_acl.py --gui
```

The Turtle GUI allows you to:
- 🔍 **Check Status**: Inspect your sandbox state without modifying any files.
- ⚡ **Fix / Repair**: Safely quarantine the corrupt file if corruption is detected.
- 📂 **Open Folder**: Open the `.sandbox` directory directly in File Explorer.
- **Settings**: Choose Codex permissions and a model on Windows, Ubuntu, or macOS.

> **Important**: Please close ChatGPT, Codex, and any active Codex sessions in VS Code before executing a fix.

ACL repair is Windows-specific. On Ubuntu/macOS the GUI provides settings editing; `--check` and `--fix` require `--force-platform` to inspect copied Windows state for testing.

---

### 2. Command-Line Interface (CLI)

#### Check Only (Dry Run)
Inspect the state file without making changes:

```powershell
python repair_acl.py --check
```

Exit codes:
- `0`: State file is healthy or does not exist (no repair needed).
- `2`: Corruption detected (repair needed).
- `1`: Error encountered (e.g., access denied, concurrent write).

#### Perform Repair
Quarantine the corrupt state file:

```powershell
python repair_acl.py --fix
```

#### JSON Output (For Automation / CI)
Output structured diagnostic results in JSON:

```powershell
python repair_acl.py --check --json
```

Example JSON response:
```json
{
  "status": "corrupt",
  "codex_home": "C:\\Users\\user\\.codex",
  "sandbox_dir": "C:\\Users\\user\\.codex\\.sandbox",
  "state_file": "C:\\Users\\user\\.codex\\.sandbox\\deny_read_acl_state.json",
  "exists": true,
  "size_bytes": 22,
  "reason": "The file contains only NUL (zero) bytes (22 bytes).",
  "can_repair": true,
  "message": "Corruption detected (22 bytes): The file contains only NUL (zero) bytes (22 bytes)."
}
```

#### Custom Codex Home Path
If your Codex data is stored in a custom location:

```powershell
python repair_acl.py --codex-home "D:\MyData\.codex" --fix
```

---

## Python API Usage

The utility can be imported and used directly in Python scripts:

```python
from pathlib import Path
from repair_acl import check_codex_state, repair_codex_state, StateStatus

# Inspect state
check = check_codex_state()
if check.status == StateStatus.CORRUPT:
    print(f"Corrupt: {check.reason}")
    # Perform safe repair
    result = repair_codex_state()
    if result.success:
        print(f"Backed up to: {result.backup_file}")
elif check.status == StateStatus.HEALTHY:
    print("State file is clean and healthy.")
```

---

## Running Unit Tests

The test suite runs against isolated temporary directories and never modifies the live system:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py"
```

## Build and publish releases

The [release workflow](.github/workflows/release.yml) tests and builds on native Windows, Ubuntu, Apple Silicon macOS, and Intel macOS runners. Each archive includes a GUI, a CLI, the README, and the license. Packaged CLI smoke tests verify config writes, reads, and ACL repair in temporary directories before upload.

Push a version tag after committing and pushing the changes to publish all four archives and their SHA-256 checksums:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

The workflow uses GitHub's built-in `GITHUB_TOKEN`; no release secret is needed. Pull requests also build and test the apps. **Actions → Build and release executables → Run workflow** builds downloadable artifacts without publishing when run on a branch; running it on an existing `v*` tag publishes that tag. Re-running a tag updates its existing release assets.

To build locally on the target OS:

```powershell
python -m pip install -r requirements-build.txt
python scripts/build_release.py --target windows-x64
```

Use `ubuntu-x64`, `macos-arm64`, or `macos-x64` on the matching native OS and CPU. Build tools use Python 3.9+; CI uses Python 3.13. Archives appear under `dist/release/`.

---

## Repository Structure

```text
resolve-acl-deny-error/
├── .github/workflows/release.yml # Native builds and tag-based releases
├── scripts/build_release.py   # Packaging and executable smoke tests
├── tests/                     # Unit test suite
│   ├── test_repair_acl.py
│   └── test_codex_config.py
├── repair_acl.py              # Core engine, programmatic API, and CLI
├── turtle_gui.py              # Interactive Turtle-based GUI
├── settings_gui.py            # Permission/model settings dialog
├── codex_config.py            # TOML-preserving settings editor
├── requirements.txt           # Settings dependency
├── requirements-build.txt     # Native packaging dependencies
├── run.bat                    # Windows launcher (launches GUI or forwards CLI flags)
├── run.sh                     # POSIX launcher
├── secrets.md                 # Security & credential audit trail
└── README.md                  # Project documentation
```
