# Codex / ChatGPT Windows ACL Error Repair Tool

A production-grade, zero-dependency utility to diagnose and repair the `helper_unknown_error: apply deny-read ACLs` error in OpenAI Codex and ChatGPT on Windows.

---

## The Problem

On Windows, Codex uses `%USERPROFILE%\.codex\.sandbox\deny_read_acl_state.json` to track deny-read ACL state across sandbox sessions. When this file becomes corrupted (such as containing only NUL bytes or truncated UTF-8 data after an unexpected shutdown or crash), Codex fails to parse the tracking JSON during startup and crashes with an ACL error.

This tool safely detects corruption in the state file and quarantines it to a timestamped backup (`.corrupt-<timestamp>-<id>.bak`), allowing Codex to cleanly regenerate its tracking state on next launch.

---

## Key Features & Safety Guarantees

- **Zero Third-Party Dependencies**: Pure Python 3.9+ standard library (`turtle`, `tkinter`, `json`, `pathlib`). No `pip install` required.
- **Interactive Turtle GUI**: Clean, modern dark-theme graphical interface with visual inspection, dry-run checking, one-click repair, and quick sandbox folder access.
- **Non-Destructive & Safe by Design**:
  - Never touches or alters valid, parseable JSON files (even with unknown future schemas).
  - Preserves original bytes and Windows file permissions in unique timestamped backups.
  - Never modifies Windows user privileges, system ACLs, or sandbox security modes.
  - Refuses symbolic links, junctions, and reparse points to prevent directory traversal.
  - Detects concurrent modifications between inspection and quarantine.
- **Automation Ready**: First-class CLI with `--check` (dry run), `--fix`, and `--json` machine-readable output.

---

## Quick Start

### 1. Launch Interactive GUI (Recommended)

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

> **Important**: Please close ChatGPT, Codex, and any active Codex sessions in VS Code before executing a fix.

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
python -m unittest discover -s tests -p "test_*.py"
```

---

## Repository Structure

```text
resolve-acl-deny-error/
├── original-project/          # Original reference implementation & tests
│   ├── repair_codex_acl.py
│   ├── test_repair_codex_acl.py
│   └── run.bat
├── tests/                     # Unit test suite
│   └── test_repair_acl.py
├── repair_acl.py              # Core engine, programmatic API, and CLI
├── turtle_gui.py              # Interactive Turtle-based GUI
├── run.bat                    # Windows launcher (launches GUI or forwards CLI flags)
├── run.sh                     # POSIX launcher
├── secrets.md                 # Security & credential audit trail
└── README.md                  # Project documentation
```
