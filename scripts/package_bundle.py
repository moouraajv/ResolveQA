#!/usr/bin/env python3
"""Builds a deterministic, bit-for-bit reproducible deployment tarball of ResolveQA backend.

Packages `src/` and `scripts/` into `dist/resolveqa-bundle.tar.gz` and computes
its SHA-256 hash for secure verification during EC2 CloudFormation bootstrap.

Determinism invariants:
  - Gzip header mtime is fixed to 0 and filename is empty.
  - Tar entries are sorted lexicographically by relative path.
  - File metadata (uid, gid, uname, gname, mtime) is normalized to fixed zeros.
  - Permissions are normalized (0o755 for executables/dirs, 0o644 for regular files).
  - Includes a resolveqa-manifest.json containing git commit SHA.
  - Rejects dirty git working trees for production builds (unless allow_dirty is set).

Does NOT perform any cloud mutation.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist"


def get_git_info(repo_root: Path) -> dict[str, Any]:
    """Retrieve git commit SHA and status for src/ and scripts/."""
    commit_sha = "unknown"
    is_dirty = False
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        commit_sha = res.stdout.strip()
    except Exception:
        pass

    try:
        status_res = subprocess.run(
            ["git", "status", "--porcelain", "src", "scripts"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        is_dirty = bool(status_res.stdout.strip())
    except Exception:
        pass

    return {"commit_sha": commit_sha, "dirty": is_dirty}


def build_bundle(
    output_path: Path | None = None,
    *,
    repo_root: Path | None = None,
    reject_dirty: bool = True,
) -> tuple[Path, str, int]:
    """Build a deterministic, reproducible tar.gz bundle of src/ and scripts/."""
    root = repo_root or REPO_ROOT
    git_info = get_git_info(root)

    if reject_dirty and git_info["dirty"]:
        raise ValueError(
            "Cannot build reproducible deployment bundle: working tree has uncommitted modifications in src/ or scripts/."
        )

    out_file = output_path or (root / "dist" / "resolveqa-bundle.tar.gz")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if out_file.exists():
        out_file.unlink()

    # Collect and sort all files deterministically
    entries: list[tuple[str, Path]] = []
    for component in ["src", "scripts"]:
        comp_dir = root / component
        if not comp_dir.is_dir():
            continue
        for child in sorted(comp_dir.rglob("*")):
            # Skip caches and compiled files
            if "__pycache__" in child.parts or child.suffix in {".pyc", ".pyo"}:
                continue
            rel_path = child.relative_to(root).as_posix()
            entries.append((rel_path, child))

    # Sort lexicographically by arcname
    entries.sort(key=lambda pair: pair[0])

    manifest_bytes = json.dumps(
        {
            "schema_version": "1.0",
            "commit_sha": git_info["commit_sha"],
            "dirty": git_info["dirty"],
            "components": ["src", "scripts"],
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")

    # Write normalized tar archive wrapped in fixed-mtime GzipFile
    with open(out_file, "wb") as raw_out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_out, mtime=0) as gz_out:
            with tarfile.open(mode="w", fileobj=gz_out) as tar:
                # 1. Add manifest
                ti_manifest = tarfile.TarInfo("resolveqa-manifest.json")
                ti_manifest.size = len(manifest_bytes)
                ti_manifest.mtime = 0
                ti_manifest.uid = 0
                ti_manifest.gid = 0
                ti_manifest.uname = ""
                ti_manifest.gname = ""
                ti_manifest.mode = 0o644
                tar.addfile(ti_manifest, io.BytesIO(manifest_bytes))

                # 2. Add sorted files
                for arcname, file_path in entries:
                    if file_path.is_dir():
                        ti = tarfile.TarInfo(arcname)
                        ti.type = tarfile.DIRTYPE
                        ti.mode = 0o755
                    else:
                        ti = tarfile.TarInfo(arcname)
                        ti.type = tarfile.REGTYPE
                        ti.size = file_path.stat().st_size
                        # Preserve executable bit
                        is_exec = os.access(file_path, os.X_OK)
                        ti.mode = 0o755 if is_exec else 0o644

                    ti.mtime = 0
                    ti.uid = 0
                    ti.gid = 0
                    ti.uname = ""
                    ti.gname = ""

                    if file_path.is_file():
                        with open(file_path, "rb") as f:
                            tar.addfile(ti, f)
                    else:
                        tar.addfile(ti)

    # Compute SHA-256 digest
    sha256 = hashlib.sha256()
    with open(out_file, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)

    digest = sha256.hexdigest()
    size_bytes = out_file.stat().st_size
    return out_file, digest, size_bytes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package ResolveQA backend code into an integrity-verified deterministic tarball"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Custom output file path (default: dist/resolveqa-bundle.tar.gz)",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow building even if working tree has unstaged edits (for test builds)",
    )
    args = parser.parse_args()

    target, digest, size_bytes = build_bundle(args.output, reject_dirty=not args.allow_dirty)
    try:
        display_target = target.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        display_target = str(target)

    print("=" * 70)
    print("ResolveQA Backend Deterministic Deployment Bundle Created")
    print(f"File:    {display_target}")
    print(f"Size:    {size_bytes} bytes")
    print(f"SHA-256: {digest}")
    print("=" * 70)
    print("Upload instructions (when authorized; uses standard AWS credential chain):")
    print(f"  aws s3 cp {display_target} s3://<ArtifactBucket>/<ArtifactKey>")
    print("-" * 70)
    print("CloudFormation parameter snippet:")
    print(f"  ParameterKey=ArtifactSha256,ParameterValue={digest}")
    print("=" * 70)


if __name__ == "__main__":
    main()
