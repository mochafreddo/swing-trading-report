"""Build disabled, unscheduled launchd plists for wrapper-only dry runs."""

from __future__ import annotations

import hashlib
import os
import plistlib
import stat
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .runner import RunKindV0
from .shadow_gate import ShadowGateManifestError, load_shadow_gate_manifest_v0


class ShadowLaunchdPackageError(ValueError):
    """One sanitized package construction failure."""


@dataclass(frozen=True, slots=True)
class ShadowLaunchdPackageFileV0:
    run_kind: RunKindV0
    basename: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ShadowLaunchdPackageResultV0:
    approval_state: str
    manifest_sha256: str
    session: date
    files: tuple[ShadowLaunchdPackageFileV0, ...]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": "PACKAGE_READY",
            "mode": "DRY_RUN_ONLY",
            "approval_state": self.approval_state,
            "manifest_sha256": self.manifest_sha256,
            "session": self.session.isoformat(),
            "lanes": [file.run_kind.value for file in self.files],
            "files": [
                {
                    "run_kind": file.run_kind.value,
                    "basename": file.basename,
                    "sha256": file.sha256,
                }
                for file in self.files
            ],
            "disabled": True,
            "scheduled": False,
            "runner_execution": False,
        }


def build_decision_board_launchd_dry_run_package_v0(
    *,
    manifest_path: str | Path,
    session: str,
    repo_root: str | Path,
    journal_dir: str | Path,
    output_dir: str | Path,
    report_dir: str | Path | None = None,
    require_approved: bool = False,
    input_ledger_path: str | Path | None = None,
    expected_action_ledger_path: str | Path | None = None,
) -> ShadowLaunchdPackageResultV0:
    if (input_ledger_path is None) != (expected_action_ledger_path is None):
        raise ShadowLaunchdPackageError("package gate ledger paths are incomplete")
    try:
        manifest_file = Path(manifest_path).resolve(strict=True)
        manifest = load_shadow_gate_manifest_v0(
            manifest_file,
            require_approved=require_approved,
            input_ledger_path=input_ledger_path,
            expected_action_ledger_path=expected_action_ledger_path,
        )
    except ShadowGateManifestError as exc:
        raise ShadowLaunchdPackageError(str(exc)) from None
    except OSError, TypeError:
        raise ShadowLaunchdPackageError("package manifest is invalid") from None
    try:
        selected_session = date.fromisoformat(session)
    except TypeError, ValueError:
        raise ShadowLaunchdPackageError("package session is invalid") from None
    if selected_session not in manifest.sessions:
        raise ShadowLaunchdPackageError("package session is outside the manifest")
    root = _require_real_directory(repo_root, "repository root")
    wrapper = root / "scripts" / "launchd" / "sab-decision-board-shadow-wrapper.sh"
    try:
        wrapper_identity = wrapper.lstat()
    except OSError:
        raise ShadowLaunchdPackageError("package wrapper is unavailable") from None
    if (
        not stat.S_ISREG(wrapper_identity.st_mode)
        or wrapper.is_symlink()
        or not os.access(wrapper, os.X_OK)
    ):
        raise ShadowLaunchdPackageError("package wrapper is unavailable")
    journal = _require_absolute_path(journal_dir, "journal directory")
    reports = _require_absolute_path(
        report_dir if report_dir is not None else root / "reports",
        "report directory",
    )
    selected_slots = tuple(
        sorted(
            (slot for slot in manifest.slots if slot.session == selected_session),
            key=lambda slot: (
                0 if slot.run_kind is RunKindV0.ENTRY else 1,
                slot.run_id,
            ),
        )
    )
    if tuple(slot.run_kind for slot in selected_slots) != (
        RunKindV0.ENTRY,
        RunKindV0.HOLDING,
    ):
        raise ShadowLaunchdPackageError("package manifest lanes are invalid")
    destination = _require_new_output_directory(output_dir)

    package_files: list[ShadowLaunchdPackageFileV0] = []
    written: list[Path] = []
    try:
        for slot in selected_slots:
            basename = (
                "com.mochafreddo.sab.decision-board."
                f"{slot.run_kind.value.lower()}-shadow-{selected_session:%Y%m%d}.plist"
            )
            payload = _plist_payload(
                root=root,
                wrapper=wrapper,
                journal_dir=journal,
                report_dir=reports,
                run_kind=slot.run_kind,
                expected_at=slot.expected_at.isoformat().replace("+00:00", "Z"),
                run_id=slot.run_id,
                grace_seconds=manifest.grace_seconds,
                stale_seconds=manifest.stale_seconds,
                manifest_path=manifest_file,
                manifest_sha256=manifest.manifest_sha256,
                input_ledger_path=(
                    None if input_ledger_path is None else Path(input_ledger_path)
                ),
                expected_action_ledger_path=(
                    None
                    if expected_action_ledger_path is None
                    else Path(expected_action_ledger_path)
                ),
            )
            encoded = plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)
            target = destination / basename
            with target.open("xb") as stream:
                stream.write(encoded)
            written.append(target)
            package_files.append(
                ShadowLaunchdPackageFileV0(
                    run_kind=slot.run_kind,
                    basename=basename,
                    sha256=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
                )
            )
    except Exception:
        for path in written:
            with suppress(OSError):
                path.unlink()
        with suppress(OSError):
            destination.rmdir()
        raise ShadowLaunchdPackageError("package files could not be written") from None
    return ShadowLaunchdPackageResultV0(
        approval_state=manifest.approval_state,
        manifest_sha256=manifest.manifest_sha256,
        session=selected_session,
        files=tuple(package_files),
    )


def _plist_payload(
    *,
    root: Path,
    wrapper: Path,
    journal_dir: Path,
    report_dir: Path,
    run_kind: RunKindV0,
    expected_at: str,
    run_id: str,
    grace_seconds: int,
    stale_seconds: int,
    manifest_path: Path,
    manifest_sha256: str,
    input_ledger_path: Path | None,
    expected_action_ledger_path: Path | None,
) -> dict[str, object]:
    runner = [
        "uv",
        "run",
        "python",
        "-m",
        "sab",
        "decision-board-shadow-live",
        "--run-kind",
        run_kind.value,
        "--run-id",
        run_id,
        "--idempotency-key",
        "sha256:" + "0" * 64,
        "--created-at",
        expected_at,
        "--sealed-input-hash",
        "sha256:" + "1" * 64,
        "--gate-manifest-sha256",
        manifest_sha256,
        "--upload-mode",
        "disabled",
        "--report-dir",
        str(report_dir),
    ]
    gate_ledger_args: list[str] = []
    if input_ledger_path is not None and expected_action_ledger_path is not None:
        gate_ledger_args = [
            "--input-ledger",
            str(input_ledger_path),
            "--expected-action-ledger",
            str(expected_action_ledger_path),
        ]
        runner.extend(
            [
                "--gate-manifest",
                str(manifest_path),
                *gate_ledger_args,
            ]
        )
    return {
        "Label": (
            "com.mochafreddo.sab.decision-board."
            f"{run_kind.value.lower()}-shadow-{run_id.rsplit('-', 1)[-1]}"
        ),
        "Disabled": True,
        "WorkingDirectory": str(root),
        "ProgramArguments": [
            str(wrapper),
            "--run-kind",
            run_kind.value,
            "--expected-at",
            expected_at,
            "--run-id",
            run_id,
            "--journal-dir",
            str(journal_dir),
            "--grace-seconds",
            str(grace_seconds),
            "--stale-seconds",
            str(stale_seconds),
            "--gate-manifest",
            str(manifest_path),
            "--gate-manifest-sha256",
            manifest_sha256,
            *gate_ledger_args,
            "--dry-run",
            "--",
            *runner,
        ],
    }


def _require_real_directory(value: str | Path, label: str) -> Path:
    try:
        path = Path(value)
        if not path.is_absolute():
            raise OSError
        identity = path.lstat()
    except OSError, TypeError:
        raise ShadowLaunchdPackageError(f"package {label} is invalid") from None
    if not stat.S_ISDIR(identity.st_mode) or path.is_symlink():
        raise ShadowLaunchdPackageError(f"package {label} is invalid")
    return path


def _require_absolute_path(value: str | Path, label: str) -> Path:
    try:
        path = Path(value)
    except TypeError:
        raise ShadowLaunchdPackageError(f"package {label} is invalid") from None
    if not path.is_absolute() or "\x00" in str(path):
        raise ShadowLaunchdPackageError(f"package {label} is invalid")
    return path


def _require_new_output_directory(value: str | Path) -> Path:
    destination = _require_absolute_path(value, "output directory")
    try:
        destination.mkdir(parents=True, exist_ok=False)
        identity = destination.lstat()
    except OSError:
        raise ShadowLaunchdPackageError(
            "package output directory is unavailable"
        ) from None
    if not stat.S_ISDIR(identity.st_mode) or destination.is_symlink():
        raise ShadowLaunchdPackageError("package output directory is unavailable")
    return destination


__all__ = [
    "ShadowLaunchdPackageError",
    "ShadowLaunchdPackageFileV0",
    "ShadowLaunchdPackageResultV0",
    "build_decision_board_launchd_dry_run_package_v0",
]
