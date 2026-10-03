"""Production-grade repair utility for corrupt Codex deny-read tracking JSON.

Resolves `helper_unknown_error: apply deny-read ACLs` caused by a corrupted
`%USERPROFILE%\\.codex\\.sandbox\\deny_read_acl_state.json` file.

Safe by design:
- Does not modify Windows ACLs or reset security permissions.
- Preserves file permissions and original bytes in a timestamped backup.
- Only quarantines verified corrupt/malformed files; healthy JSON is never touched.
- Detects symlinks/reparse points to avoid directory traversal.
- Detects concurrent modification between diagnosis and rename.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import os
from pathlib import Path
import stat
import sys
from typing import Optional, Sequence
from uuid import uuid4

STATE_NAME = "deny_read_acl_state.json"
MAX_STATE_BYTES = 16 * 1024 * 1024  # 16 MiB limit

logger = logging.getLogger("codex_acl_repair")


class RepairError(Exception):
    """Raised when an operation cannot safely proceed."""


class StateStatus(str, Enum):
    HEALTHY = "healthy"
    CORRUPT = "corrupt"
    NOT_FOUND = "not_found"
    ERROR = "error"


@dataclass
class CheckResult:
    status: StateStatus
    codex_home: Path
    sandbox_dir: Path
    state_file: Path
    exists: bool = False
    size_bytes: int = 0
    reason: Optional[str] = None
    can_repair: bool = False
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "codex_home": str(self.codex_home),
            "sandbox_dir": str(self.sandbox_dir),
            "state_file": str(self.state_file),
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "reason": self.reason,
            "can_repair": self.can_repair,
            "message": self.message,
        }


@dataclass
class RepairResult:
    success: bool
    status: StateStatus
    check: CheckResult
    backup_file: Optional[Path] = None
    message: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "status": self.status.value,
            "check": self.check.to_dict(),
            "backup_file": str(self.backup_file) if self.backup_file else None,
            "message": self.message,
            "error": self.error,
        }


def default_codex_home() -> Path:
    """Return configured CODEX_HOME or %USERPROFILE%/.codex."""
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def get_paths(codex_home: Optional[Path] = None) -> tuple[Path, Path, Path]:
    """Resolve home, sandbox dir, and state file path."""
    home = (codex_home or default_codex_home()).expanduser().resolve()
    sandbox = home / ".sandbox"
    state_file = sandbox / STATE_NAME
    return home, sandbox, state_file


def is_link(info: os.stat_result) -> bool:
    """Check if the path is a symbolic link or Windows reparse point."""
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def fingerprint(info: os.stat_result) -> tuple:
    """Return unique identity tuple for concurrent modification detection."""
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def read_snapshot(path: Path) -> tuple[bytes, tuple]:
    """Safely read state file ensuring it's a regular file and not modified during read."""
    before = path.lstat()
    if is_link(before) or not stat.S_ISREG(before.st_mode):
        raise RepairError("The state path is a link or is not a regular file; left untouched.")
    if before.st_size > MAX_STATE_BYTES:
        raise RepairError(f"State file exceeds {MAX_STATE_BYTES // (1024 * 1024)} MiB; repair refused.")

    with path.open("rb") as stream:
        raw = stream.read(MAX_STATE_BYTES + 1)
        opened = os.fstat(stream.fileno())
    after = path.lstat()

    if (
        len(raw) > MAX_STATE_BYTES
        or fingerprint(before) != fingerprint(opened)
        or fingerprint(before) != fingerprint(after)
        or is_link(after)
    ):
        raise RepairError("State file changed while being read. Close Codex/VS Code and retry.")
    return raw, fingerprint(after)


def detect_corruption(raw: bytes) -> Optional[str]:
    """Inspect raw bytes and return the corruption reason, or None if valid JSON."""
    if not raw:
        return "The file is empty (0 bytes)."
    if not raw.strip(b"\x00"):
        return f"The file contains only NUL (zero) bytes ({len(raw)} bytes)."

    class NonJsonConstant(ValueError):
        pass

    def reject_constant(value: str) -> None:
        raise NonJsonConstant("Non-JSON numeric constant: " + value)

    try:
        # Codex/Rust strictly expects UTF-8 JSON.
        json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except UnicodeDecodeError:
        return "The file is not valid UTF-8."
    except json.JSONDecodeError as error:
        return f"Malformed JSON at line {error.lineno}, column {error.colno}."
    except NonJsonConstant:
        return "The file contains a non-JSON numeric constant (e.g., NaN or Infinity)."
    except (RecursionError, ValueError) as error:
        raise RepairError("JSON exceeds parser nesting limits; left untouched.") from error

    return None


def check_codex_state(codex_home: Optional[Path] = None) -> CheckResult:
    """Non-destructive inspection of the Codex deny-read ACL state file."""
    home, sandbox, state_file = get_paths(codex_home)

    if not home.is_dir():
        return CheckResult(
            status=StateStatus.NOT_FOUND,
            codex_home=home,
            sandbox_dir=sandbox,
            state_file=state_file,
            exists=False,
            message=f"Codex home directory does not exist: {home}",
        )

    try:
        sandbox_info = sandbox.lstat()
    except FileNotFoundError:
        return CheckResult(
            status=StateStatus.NOT_FOUND,
            codex_home=home,
            sandbox_dir=sandbox,
            state_file=state_file,
            exists=False,
            message="No .sandbox directory found. Codex has not initialized sandbox state yet.",
        )

    if is_link(sandbox_info) or not stat.S_ISDIR(sandbox_info.st_mode):
        raise RepairError("The .sandbox path is a link or is not a directory; left untouched.")

    try:
        raw, _ = read_snapshot(state_file)
    except FileNotFoundError:
        return CheckResult(
            status=StateStatus.NOT_FOUND,
            codex_home=home,
            sandbox_dir=sandbox,
            state_file=state_file,
            exists=False,
            message="No deny_read_acl_state.json exists. Nothing to repair.",
        )

    reason = detect_corruption(raw)
    if reason is None:
        return CheckResult(
            status=StateStatus.HEALTHY,
            codex_home=home,
            sandbox_dir=sandbox,
            state_file=state_file,
            exists=True,
            size_bytes=len(raw),
            reason=None,
            can_repair=False,
            message=f"State file is valid parseable JSON ({len(raw)} bytes). No corruption detected.",
        )

    return CheckResult(
        status=StateStatus.CORRUPT,
        codex_home=home,
        sandbox_dir=sandbox,
        state_file=state_file,
        exists=True,
        size_bytes=len(raw),
        reason=reason,
        can_repair=True,
        message=f"Corruption detected ({len(raw)} bytes): {reason}",
    )


def repair_codex_state(codex_home: Optional[Path] = None, check_only: bool = False) -> RepairResult:
    """Diagnose and safely repair corrupt Codex state file.

    Returns RepairResult with structured outcome.
    """
    check = check_codex_state(codex_home)

    if not check.can_repair:
        if check.status == StateStatus.HEALTHY:
            return RepairResult(
                success=True,
                status=check.status,
                check=check,
                message="File is healthy. No repair was necessary.",
            )
        return RepairResult(
            success=True,
            status=check.status,
            check=check,
            message=check.message,
        )

    if check_only:
        return RepairResult(
            success=False,
            status=StateStatus.CORRUPT,
            check=check,
            message=f"Check only: {check.message}. Run with --fix to repair.",
        )

    # Re-verify immediately before rename to avoid race conditions.
    path = check.state_file
    latest, _ = read_snapshot(path)
    latest_reason = detect_corruption(latest)
    if latest_reason is None:
        raise RepairError("State file became valid while diagnosing. Close Codex and retry.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.name}.corrupt-{stamp}-{uuid4().hex}.bak")

    # Atomic rename in same directory preserves security attributes & permissions.
    path.rename(backup)
    logger.info("Quarantined corrupt file to %s", backup)

    return RepairResult(
        success=True,
        status=StateStatus.HEALTHY,
        check=check,
        backup_file=backup,
        message=(
            f"Successfully repaired! Corrupt file quarantined to:\n  {backup.name}\n"
            "Codex will automatically recreate a fresh state file on next command."
        ),
    )


def launch_gui(codex_home: Optional[Path] = None) -> int:
    """Launch the interactive Turtle UI."""
    try:
        from turtle_gui import run_turtle_ui
        run_turtle_ui(codex_home)
        return 0
    except Exception as exc:
        logger.error("Failed to launch GUI: %s", exc)
        print(f"Error launching GUI: {exc}", file=sys.stderr)
        return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose and repair corrupt Codex deny-read ACL state files."
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=None,
        help="Codex data folder (default: CODEX_HOME, or %%USERPROFILE%%\\.codex)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        "--dry-run",
        action="store_true",
        dest="check_only",
        help="Check only without altering files; exit code 2 if corruption found",
    )
    group.add_argument(
        "--fix",
        action="store_true",
        help="Perform repair if corruption is detected",
    )
    group.add_argument(
        "--gui",
        action="store_true",
        help="Launch the interactive Turtle graphical user interface",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results in JSON format for automation",
    )
    parser.add_argument(
        "--force-platform",
        action="store_true",
        help="Allow running on non-Windows platforms (primarily for testing)",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="Keep console open with a prompt after execution",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    try:
        if os.name != "nt" and not args.force_platform:
            raise RepairError(
                "This utility is intended for Windows Codex sandboxes. Use --force-platform to override."
            )

        # If --gui requested, launch Turtle GUI
        if args.gui:
            return launch_gui(args.codex_home)

        # If run with no explicit mode and stdin is a TTY and no args were given, default to GUI if available
        if (argv is None or len(argv) == 0) and not (args.check_only or args.fix or args.json_output):
            if sys.stdin and sys.stdin.isatty():
                print("No mode specified. Launching Turtle GUI...")
                return launch_gui(args.codex_home)

        # CLI execution
        if args.check_only:
            result = repair_codex_state(args.codex_home, check_only=True)
            if args.json_output:
                print(json.dumps(result.to_dict(), indent=2))
            else:
                print(f"Target: {result.check.state_file}")
                print(f"Status: {result.status.value.upper()}")
                print(result.message)
            return 2 if result.status == StateStatus.CORRUPT else 0

        # Fix or default CLI run
        result = repair_codex_state(args.codex_home, check_only=False)
        if args.json_output:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"Target: {result.check.state_file}")
            print(f"Status: {result.status.value.upper()}")
            print(result.message)
            if result.backup_file:
                print(f"Backup location: {result.backup_file}")
        return 0

    except PermissionError as error:
        msg = f"Access denied: {error.filename or error}. Close Codex/VS Code and try again."
        logger.error(msg)
        if args.json_output:
            print(json.dumps({"success": False, "error": msg}))
        else:
            print(f"\n[ERROR] {msg}", file=sys.stderr)
        return 1
    except (RepairError, OSError) as error:
        logger.error("Stopped: %s", error)
        if args.json_output:
            print(json.dumps({"success": False, "error": str(error)}))
        else:
            print(f"\n[STOPPED] {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.", file=sys.stderr)
        return 130
    finally:
        if args.pause and sys.stdin and sys.stdin.isatty():
            try:
                input("\nPress Enter to close...")
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    sys.exit(main())
