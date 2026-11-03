#!/usr/bin/env python3
"""Publish a verified large DOOM CoMaps bundle as sub-2 GiB GitHub Release assets.

Requires a successfully repacked tar.gz and its SHA-256 file. Never compiles.
Creates a draft release first, publishing only after every part and manifest
is uploaded. A retry of an already published tag safely fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

PART_BYTES = 1536 * 1024 * 1024
READ_BYTES = 8 * 1024 * 1024
MAX_BYTES = 7 * 1024**3
PIN = "bf20d1e7460fb08e5702514881d76cfa047caa00"
BUNDLE_NAME = "doom-ios-native-slim.tar.gz"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(READ_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_input(bundle: Path, checksum: Path) -> tuple[str, int]:
    size = bundle.stat().st_size
    if not 0 < size < MAX_BYTES:
        raise ValueError(f"Native bundle has invalid size: {size}")
    expected, *tail = checksum.read_text(encoding="utf-8").split()
    if not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
        raise ValueError("Invalid SHA-256 checksum file")
    if tail and tail[0].lstrip("*") != bundle.name:
        raise ValueError("Checksum filename does not match native bundle")
    actual = sha256_file(bundle)
    if actual != expected.lower():
        raise ValueError("Native bundle failed source checksum verification")
    return actual, size


def upload(tag: str, files: list[Path], repo: str) -> None:
    for attempt in range(3):
        result = subprocess.run(
            ["gh", "release", "upload", tag, *map(str, files), "--repo", repo],
            check=False,
        )
        if result.returncode == 0:
            return
        if attempt < 2:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"GitHub Release upload failed for {files}")


def split_and_upload(bundle: Path, folder: Path, tag: str, repo: str,
                     *, dry_run: bool = False, part_bytes: int = PART_BYTES) -> list[dict]:
    parts = []
    with bundle.open("rb") as source:
        for i in range((bundle.stat().st_size + part_bytes - 1) // part_bytes):
            name = f"{BUNDLE_NAME}.part{i:03d}"
            path = folder / name
            digest = hashlib.sha256()
            length = 0
            with path.open("wb") as output:
                while length < part_bytes:
                    chunk = source.read(min(READ_BYTES, part_bytes - length))
                    if not chunk:
                        break
                    digest.update(chunk)
                    output.write(chunk)
                    length += len(chunk)
            if not length:
                raise RuntimeError("Unexpected zero-byte release part")
            parts.append({"name": name, "sha256": digest.hexdigest(), "size": length})
            if not dry_run:
                upload(tag, [path], repo)
            path.unlink()
    return parts


def publish(bundle: Path, checksum: Path, repo: str, run_id: str,
            *, dry_run: bool = False, part_bytes: int = PART_BYTES) -> dict:
    if not re.fullmatch(r"\d{5,15}", run_id):
        raise ValueError("Missing real successful repack run ID")
    if repo != "ram-labz/doom-native-builder":
        raise ValueError("Unexpected target repository")
    digest, size = verify_input(bundle, checksum)
    tag = f"doom-ios-comaps-{PIN[:12]}-run-{run_id}"
    if not dry_run:
        result = subprocess.run(
            ["gh", "release", "view", tag, "--repo", repo],
            capture_output=True, check=False,
        )
        if result.returncode == 0:
            raise RuntimeError(f"Release {tag} already exists. Refusing overwrite.")
        subprocess.run([
            "gh", "release", "create", tag, "--repo", repo, "--draft",
            "--title", f"DOOM native iOS CoMaps {PIN[:12]} ({run_id})",
            "--notes", "Pinned source-built CoMaps and DuckDB iOS frameworks for DOOM. "
                       "Release assets are split below 2 GiB. No native rebuild."
        ], check=True)
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        parts = split_and_upload(bundle, folder, tag, repo, dry_run=dry_run,
                                 part_bytes=part_bytes)
        if sum(part["size"] for part in parts) != size:
            raise RuntimeError("Release part length mismatch")
        manifest = {
            "schema": 1,
            "bundle": BUNDLE_NAME,
            "bundle_sha256": digest,
            "bundle_bytes": size,
            "pinned_native_revision": PIN,
            "source_repack_run_id": run_id,
            "parts": parts,
        }
        destination = folder / "doom-ios-native-manifest.json"
        destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
        if not dry_run:
            upload(tag, [destination, checksum], repo)
            subprocess.run([
                "gh", "release", "edit", tag, "--repo", repo,
                "--draft=false",
            ], check=True)
    manifest_url = (f"https://github.com/{repo}/releases/download/{tag}/"
                    "doom-ios-native-manifest.json")
    print(f"DOOM_IOS_NATIVE_BUNDLE_MANIFEST_URL={manifest_url}", flush=True)
    print(f"DOOM_IOS_NATIVE_BUNDLE_SHA256={digest}", flush=True)
    print(f"RELEASE_PARTS={len(parts)}", flush=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--sha-file", type=Path, required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    publish(args.bundle, args.sha_file, args.repo, args.run_id)


if __name__ == "__main__":
    main()
