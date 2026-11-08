#!/usr/bin/env python3
"""Builds a versioned, reproducible deployment tarball of ResolveQA backend.

Packages `src/` and `scripts/` into `dist/resolveqa-bundle.tar.gz` and computes
its SHA256 hash for secure verification during EC2 CloudFormation bootstrap.

Does NOT perform any cloud mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist"


def build_bundle(output_path: Path | None = None) -> tuple[Path, str, int]:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    target = output_path or (DIST_DIR / "resolveqa-bundle.tar.gz")

    if target.exists():
        target.unlink()

    # Package src/ and scripts/
    with tarfile.open(target, "w:gz") as tar:
        for folder in ["src", "scripts"]:
            folder_path = REPO_ROOT / folder
            if folder_path.is_dir():
                tar.add(
                    folder_path,
                    arcname=folder,
                    filter=lambda tarinfo: None
                    if "__pycache__" in tarinfo.name or tarinfo.name.endswith(".pyc")
                    else tarinfo,
                )

    # Compute SHA-256
    sha256 = hashlib.sha256()
    with open(target, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)

    digest = sha256.hexdigest()
    size_bytes = target.stat().st_size
    return target, digest, size_bytes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package ResolveQA backend code into an integrity-verified tarball"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Custom output file path (default: dist/resolveqa-bundle.tar.gz)",
    )
    args = parser.parse_args()

    target, digest, size_bytes = build_bundle(args.output)

    print("=" * 70)
    print("ResolveQA Backend Deployment Bundle Created")
    print(f"File:    {target}")
    print(f"Size:    {size_bytes} bytes")
    print(f"SHA-256: {digest}")
    print("=" * 70)
    print("Upload instructions (when authorized):")
    print(f"  aws s3 cp {target} s3://<ArtifactBucket>/<ArtifactKey> ")
    print("-" * 70)
    print("CloudFormation parameter snippet:")
    print(f"  ParameterKey=ArtifactSha256,ParameterValue={digest}")
    print("=" * 70)


if __name__ == "__main__":
    main()
