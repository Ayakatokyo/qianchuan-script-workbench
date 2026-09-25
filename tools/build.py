"""Build this standalone Skill using only its own explicit packaging.json."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import zipfile
from typing import Any


_PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _relative(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"{label} must not be absolute or escape the project")
    return path


def _source_path(project_root: Path, source: str) -> Path:
    relative = _relative(source, "source")
    raw = project_root / Path(*relative.parts)
    if any(part.is_symlink() for part in [raw, *raw.parents] if part != project_root):
        raise ValueError(f"symlink source is not allowed: {source}")
    path = raw.resolve()
    if not path.is_relative_to(project_root):
        raise ValueError("source path escapes the project")
    if path.is_symlink():
        raise ValueError(f"symlink source is not allowed: {source}")
    if not path.is_file():
        raise ValueError(f"allowlisted source is not a file: {source}")
    return path


def build_package(project_root: Path, manifest_path: Path, dist_dir: Path) -> Path:
    project_root = Path(project_root).resolve()
    manifest_path = Path(manifest_path).resolve()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read package manifest: {manifest_path.name}") from exc
    package = payload.get("package") if isinstance(payload, dict) else None
    if not isinstance(package, str) or not _PACKAGE_NAME.fullmatch(package):
        raise ValueError("manifest package must be a safe lowercase package name")
    entries = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("manifest files must be a non-empty explicit list")

    resolved_entries: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("manifest file entries must be objects")
        source_name = item.get("source")
        source = _source_path(project_root, source_name)
        destination = _relative(item.get("destination"), "destination")
        if source.suffix == ".py":
            own_scripts = "scripts"
            if (
                PurePosixPath(source_name).parent.as_posix() != own_scripts.rstrip("/")
                or destination.parent.as_posix() != "scripts"
            ):
                raise ValueError(f"Python runtime must live in its own Skill scripts directory: {source_name}")
        archive_name = destination.as_posix() if payload.get("rootLayout") == "flat" else f"{package}/{destination.as_posix()}"
        if archive_name in seen:
            raise ValueError(f"duplicate archive path: {archive_name}")
        seen.add(archive_name)
        resolved_entries.append((archive_name, source))

    dist_dir = Path(dist_dir).resolve()
    dist_dir.mkdir(parents=True, exist_ok=True)
    output = dist_dir / f"{package}.zip"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{package}.", suffix=".tmp", dir=dist_dir)
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for archive_name, source in resolved_entries:
                info = zipfile.ZipInfo(archive_name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, source.read_bytes())
        with zipfile.ZipFile(temporary) as archive:
            expected = {name: source for name, source in resolved_entries}
            if archive.testzip() is not None or set(archive.namelist()) != set(expected):
                raise ValueError("Archive integrity/allowlist failure")
            if any(archive.read(name) != source.read_bytes() for name, source in expected.items()):
                raise ValueError("Source changed during build")
        os.replace(temporary, output)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    return output


def _main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--project-root", type=Path, default=default_root)
    parser.add_argument("--dist-dir", type=Path)
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    manifest = args.manifest or root / "packaging.json"
    destination = args.dist_dir or root / "dist"
    print(build_package(root, manifest, destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["build_package"]
