"""Hardened local storage primitives for E13 shadow artifacts.

E13 has exactly one mutable namespace: the canonical runtime ``data``
directory.  The helpers in this module deliberately reject path aliases
(symlinks and hardlinks) and make file replacement durable before returning.
"""

from __future__ import annotations

import errno
import os
import stat
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from price_action.runtime_paths import REPO_ROOT, resolve_runtime_root

MutationCallback = Callable[[Path], None]


def canonical_e13_data_root() -> Path:
    """Return the sole directory in which E13 may own mutable artifacts."""
    runtime_root = resolve_runtime_root(REPO_ROOT)
    return Path(os.path.abspath(runtime_root / "data"))


def e13_global_lock_path() -> Path:
    """Return the config-independent process lease path."""
    return canonical_e13_data_root() / ".e13_shadow.writer.lock"


def e13_transaction_path() -> Path:
    """Return the durable recovery record shared by every E13 config."""
    return canonical_e13_data_root() / ".e13_shadow.transaction.json"


def e13_policy_migration_root() -> Path:
    """Return the canonical backup/audit namespace for policy migrations."""
    return canonical_e13_data_root() / "e13-policy-migrations"


def e13_policy_migration_transaction_path() -> Path:
    """Return the durable recovery record for one provenance migration."""
    return canonical_e13_data_root() / ".e13_shadow.policy_migration.transaction.json"


def e13_policy_migration_audit_path() -> Path:
    """Return the append-only logical audit artifact for provenance migrations."""
    return e13_policy_migration_root() / "audit.jsonl"


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _require_safe_directory(path: Path, *, field: str) -> None:
    info = _lstat(path)
    if info is None:
        raise ValueError(f"{field} does not exist: {path}")
    if stat.S_ISLNK(info.st_mode):
        raise ValueError(f"{field} must not be a symlink: {path}")
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"{field} must be a directory: {path}")
    if stat.S_IMODE(info.st_mode) & (stat.S_IWGRP | stat.S_IWOTH):
        raise ValueError(f"{field} must not be group/world writable: {path}")


def ensure_canonical_e13_data_root() -> Path:
    """Create and validate the canonical runtime data directory."""
    root = canonical_e13_data_root()
    existed = _lstat(root) is not None
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require_safe_directory(root, field="canonical E13 data root")
    if not existed:
        fsync_directory(root.parent)
    return root


def _lexical_absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(Path(path).expanduser()))


def _require_under_data_root(path: Path, *, field: str) -> Path:
    root = canonical_e13_data_root()
    candidate = _lexical_absolute(path)
    if candidate == root or not candidate.is_relative_to(root):
        raise ValueError(f"{field} must be below canonical E13 data root: {root}")
    return candidate


def _validate_parent_chain(path: Path, *, field: str, create: bool) -> None:
    root = canonical_e13_data_root()
    if create:
        ensure_canonical_e13_data_root()
    else:
        root_info = _lstat(root)
        if root_info is not None:
            _require_safe_directory(root, field="canonical E13 data root")

    current = root
    for part in path.parent.relative_to(root).parts:
        current /= part
        info = _lstat(current)
        if info is None and create:
            current.mkdir(mode=0o700)
            fsync_directory(current.parent)
            info = _lstat(current)
        if info is None:
            # Missing future parents are acceptable while loading policy. They
            # are created component-by-component immediately before mutation.
            continue
        _require_safe_directory(current, field=f"{field} parent")


def _validate_existing_file(path: Path, *, field: str) -> os.stat_result | None:
    info = _lstat(path)
    if info is None:
        return None
    if stat.S_ISLNK(info.st_mode):
        raise ValueError(f"{field} must not be a symlink: {path}")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{field} must be a regular file: {path}")
    if info.st_nlink != 1:
        raise ValueError(f"{field} must not be hard-linked: {path}")
    if info.st_uid != os.geteuid():
        raise ValueError(f"{field} must be owned by the current uid: {path}")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError(f"{field} must have safe mode 0600: {path}")
    return info


def validate_e13_artifact_path(
    path: str | Path,
    *,
    field: str,
    must_exist: bool = False,
    create_parent: bool = False,
) -> Path:
    """Validate one E13 file path without following aliases."""
    candidate = _require_under_data_root(_lexical_absolute(path), field=field)
    _validate_parent_chain(candidate, field=field, create=create_parent)
    info = _validate_existing_file(candidate, field=field)
    if must_exist and info is None:
        raise FileNotFoundError(candidate)
    return candidate


def resolve_e13_artifact_path(value: Any, *, field: str) -> Path:
    """Resolve a YAML path against the runtime root, then enforce containment."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty path")
    raw = Path(value.strip())
    if raw.is_absolute() or raw.expanduser().is_absolute():
        raise ValueError(f"{field} must be a relative path below canonical E13 data root")
    if ".." in raw.parts:
        raise ValueError(f"{field} must not contain path traversal")
    raw = resolve_runtime_root(REPO_ROOT) / raw
    return validate_e13_artifact_path(raw, field=field)


def secure_read_text(path: str | Path, *, field: str) -> str:
    """Read a validated regular file through a no-follow descriptor."""
    candidate = validate_e13_artifact_path(path, field=field, must_exist=True)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(candidate, flags)
    try:
        opened = os.fstat(fd)
        current = candidate.lstat()
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise ValueError(f"{field} must be an unlinked regular file: {candidate}")
        if opened.st_uid != os.geteuid():
            raise ValueError(f"{field} must be owned by the current uid: {candidate}")
        if stat.S_IMODE(opened.st_mode) != 0o600:
            raise ValueError(f"{field} must have safe mode 0600: {candidate}")
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError(f"{field} changed while it was opened: {candidate}")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            return handle.read()
    finally:
        if fd >= 0:
            os.close(fd)


def fsync_directory(path: str | Path) -> None:
    """Make namespace changes in one directory durable."""
    directory = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_text(
    path: str | Path,
    payload: str,
    *,
    field: str,
    on_mutation: MutationCallback | None = None,
) -> Path:
    """Atomically replace a safe artifact and fsync its parent directory."""
    candidate = validate_e13_artifact_path(
        path,
        field=field,
        create_parent=True,
    )
    fd, raw_tmp = tempfile.mkstemp(
        prefix=f".{candidate.name}.",
        suffix=".tmp",
        dir=str(candidate.parent),
        text=True,
    )
    tmp_path = Path(raw_tmp)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Reject an alias that appeared after the initial validation rather
        # than silently replacing it.
        validate_e13_artifact_path(candidate, field=field, create_parent=True)
        os.replace(tmp_path, candidate)
        if on_mutation is not None:
            on_mutation(candidate)
        fsync_directory(candidate.parent)
        validate_e13_artifact_path(candidate, field=field, must_exist=True)
        return candidate
    except Exception:
        with suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise
    finally:
        if fd >= 0:
            os.close(fd)


def durable_unlink(
    path: str | Path,
    *,
    field: str,
    on_mutation: MutationCallback | None = None,
) -> bool:
    """Remove a validated artifact and durably record the directory change."""
    candidate = validate_e13_artifact_path(path, field=field)
    if _lstat(candidate) is None:
        return False
    validate_e13_artifact_path(candidate, field=field, must_exist=True)
    try:
        os.unlink(candidate)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return False
        raise
    if on_mutation is not None:
        on_mutation(candidate)
    fsync_directory(candidate.parent)
    return True


__all__ = [
    "atomic_write_text",
    "canonical_e13_data_root",
    "durable_unlink",
    "e13_global_lock_path",
    "e13_policy_migration_audit_path",
    "e13_policy_migration_root",
    "e13_policy_migration_transaction_path",
    "e13_transaction_path",
    "ensure_canonical_e13_data_root",
    "fsync_directory",
    "resolve_e13_artifact_path",
    "secure_read_text",
    "validate_e13_artifact_path",
]
