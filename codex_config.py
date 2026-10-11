"""Read and update user-level Codex settings without discarding other TOML data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Optional
from uuid import uuid4

APPROVAL_POLICIES = ("on-request", "never")
APPROVAL_REVIEWERS = ("user", "auto_review")
SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")
PERMISSION_LEVELS = {
    "read-only": ("on-request", "user", "read-only"),
    "workspace": ("on-request", "user", "workspace-write"),
    "approve-for-me": ("on-request", "auto_review", "workspace-write"),
    "workspace-no-approvals": ("never", "user", "workspace-write"),
    "full-access": ("never", "user", "danger-full-access"),
}
MAX_CONFIG_BYTES = 1024 * 1024
EDITABLE_KEYS = ("approval_policy", "approvals_reviewer", "sandbox_mode", "model")


class ConfigError(Exception):
    """A configuration update cannot safely proceed."""


def _tomlkit():
    try:
        import tomlkit
    except ImportError as exc:
        raise ConfigError(
            "The settings editor needs tomlkit. Install with: python -m pip install -r requirements.txt"
        ) from exc
    return tomlkit


def config_path(codex_home: Optional[Path] = None) -> Path:
    home = codex_home if codex_home is not None else Path(
        os.environ.get("CODEX_HOME") or Path.home() / ".codex"
    )
    # Do not resolve away links before checking them.
    return Path(os.path.abspath(home.expanduser())) / "config.toml"


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _check_parents(path: Path) -> None:
    for parent in path.parents:
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        if _is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise ConfigError(f"Config directory is a link or is not a directory: {parent}")


def _identity(info: os.stat_result) -> tuple:
    # Windows fstat reports creation time in st_ctime while lstat uses change time
    # on recent Python versions; compare fields with consistent semantics.
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _snapshot(path: Path) -> tuple[Optional[bytes], Optional[tuple]]:
    _check_parents(path)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None, None
    if _is_link(before) or not stat.S_ISREG(before.st_mode):
        raise ConfigError("config.toml is a link or is not a regular file; left untouched.")
    if before.st_size > MAX_CONFIG_BYTES:
        raise ConfigError("config.toml exceeds 1 MiB; left untouched.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_CONFIG_BYTES + 1)
        opened = os.fstat(stream.fileno())
    after = path.lstat()
    if (len(raw) > MAX_CONFIG_BYTES or _is_link(after)
            or _identity(before) != _identity(opened) or _identity(before) != _identity(after)):
        raise ConfigError("config.toml changed while being read. Close Codex and retry.")
    return raw, _identity(after)


def _parse(raw: Optional[bytes]):
    tomlkit = _tomlkit()
    try:
        return tomlkit.parse(raw.decode("utf-8") if raw is not None else "")
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ConfigError("config.toml is not valid UTF-8 TOML; left untouched.") from exc


@dataclass
class ConfigResult:
    config_file: Path
    settings: dict
    changed: bool = False
    backup_file: Optional[Path] = None

    def to_dict(self) -> dict:
        return {
            "config_file": str(self.config_file),
            "settings": self.settings,
            "changed": self.changed,
            "backup_file": str(self.backup_file) if self.backup_file else None,
        }


def _settings(document) -> dict:
    # Return only these settings, never unrelated provider credentials.
    return {key: document[key].unwrap() for key in EDITABLE_KEYS if key in document}


def read_codex_config(codex_home: Optional[Path] = None) -> ConfigResult:
    path = config_path(codex_home)
    raw, _ = _snapshot(path)
    return ConfigResult(path, _settings(_parse(raw)))


def update_codex_config(
    codex_home: Optional[Path] = None, *, permission_level: Optional[str] = None,
    approval_policy: Optional[str] = None, approvals_reviewer: Optional[str] = None,
    sandbox_mode: Optional[str] = None, model: Optional[str] = None,
) -> ConfigResult:
    """Update only explicitly selected defaults, backing up an existing file first."""
    if permission_level is not None:
        if permission_level not in PERMISSION_LEVELS:
            raise ConfigError(f"Unknown permission level: {permission_level}")
        if any(value is not None for value in (approval_policy, approvals_reviewer, sandbox_mode)):
            raise ConfigError("Choose a permission level or individual permission settings, not both.")
        approval_policy, approvals_reviewer, sandbox_mode = PERMISSION_LEVELS[permission_level]
    updates = {}
    for key, value, choices in (
        ("approval_policy", approval_policy, APPROVAL_POLICIES),
        ("approvals_reviewer", approvals_reviewer, APPROVAL_REVIEWERS),
        ("sandbox_mode", sandbox_mode, SANDBOX_MODES),
    ):
        if value is not None:
            if value not in choices:
                raise ConfigError(f"Unsupported {key}: {value}")
            updates[key] = value
    if model is not None:
        model = model.strip()
        if not model or any(ord(char) < 32 or ord(char) == 127 for char in model):
            raise ConfigError("Model must be a non-empty model ID without control characters.")
        updates["model"] = model
    if not updates:
        raise ConfigError("Select at least one permission setting or model to save.")

    path = config_path(codex_home)
    original, identity = _snapshot(path)
    document = _parse(original)
    if sandbox_mode is not None and "default_permissions" in document:
        raise ConfigError(
            "This config uses default_permissions, which cannot be combined with sandbox_mode. "
            "Edit the permission profile in Codex, or remove default_permissions before choosing a sandbox mode."
        )
    if all(key in document and document[key] == value for key, value in updates.items()):
        return ConfigResult(path, _settings(document))
    for key, value in updates.items():
        document[key] = value
    updated = _tomlkit().dumps(document).encode("utf-8")
    if len(updated) > MAX_CONFIG_BYTES:
        raise ConfigError("Updated config.toml would exceed 1 MiB; left untouched.")
    _parse(updated)

    path.parent.mkdir(parents=True, exist_ok=True)
    _check_parents(path)
    staged = None
    backup = None
    try:
        fd, name = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=path.parent)
        staged = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if original is not None:
            shutil.copymode(path, staged, follow_symlinks=False)
        current, current_identity = _snapshot(path)
        if current != original or current_identity != identity:
            raise ConfigError("config.toml changed before saving. Reload settings and retry.")
        if original is not None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = path.with_name(f"config.toml.backup-{stamp}-{uuid4().hex}.bak")
            # Exclusive creation avoids overwriting any earlier backup.
            backup_fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(backup_fd, "wb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            shutil.copymode(path, backup, follow_symlinks=False)
        # Recheck after writing the backup as another application may have saved.
        current, current_identity = _snapshot(path)
        if current != original or current_identity != identity:
            raise ConfigError("config.toml changed before saving. Reload settings and retry.")
        os.replace(staged, path)
        staged = None
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    return ConfigResult(path, _settings(document), changed=True, backup_file=backup)
