#!/usr/bin/env python3
"""Read-only streaming inspection of DOOM's already published iOS CoMaps TAR.

Do not extract, recompile, upload or publish. Run only after whole-archive
SHA-256 verification. This is a free Linux preflight for the signed Mac build.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import plistlib
import sys
import tarfile


def audit(bundle: Path, restore_path: Path) -> dict:
    spec = importlib.util.spec_from_file_location("doom_restore_audit", restore_path)
    restore = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(restore)
    required = set(restore.REQUIRED)
    seen = set()
    arches = {}
    native_candidates = {}
    total = 0
    count = 0
    source = ".native_build/agus_maps_flutter"
    with tarfile.open(bundle, mode="r|gz") as archive:
        for entry in archive:
            count += 1
            name = entry.name.removeprefix("./")
            restore.validate_members([entry])
            if not entry.isfile():
                continue
            total += entry.size
            if total > restore.MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Native package exceeds the permitted unpacked size")
            if name in required:
                if entry.size == 0:
                    raise ValueError(f"Required native file is empty: {name}")
                seen.add(name)
                if name.endswith("/Info.plist") and "/ios/Frameworks/" in name:
                    content = archive.extractfile(entry).read()
                    info = plistlib.loads(content)
                    libs = info.get("AvailableLibraries", [])
                    if not any(
                        l.get("SupportedPlatform") == "ios"
                        and not l.get("SupportedPlatformVariant")
                        and "arm64" in l.get("SupportedArchitectures", [])
                        for l in libs
                    ):
                        raise ValueError(f"No iOS arm64 device slice in {name}")
                    device = next(
                        l for l in libs
                        if l.get("SupportedPlatform") == "ios"
                        and not l.get("SupportedPlatformVariant")
                        and "arm64" in l.get("SupportedArchitectures", [])
                    )
                    arches[name] = (device["LibraryIdentifier"], device["LibraryPath"])
            # XCFrameworks can contain .a static archives, not just .framework
            # bundles. Follow their actual Info.plist LibraryPath and inspect
            # their Mach-O/archive magic instead of assuming a hard-coded name.
            if name.startswith(source + "/ios/Frameworks/") and ".xcframework/" in name:
                if entry.size >= 4096 and (
                    name.endswith(".a")
                    or name.endswith(".dylib")
                    or ".framework/" in name
                ):
                    handle = archive.extractfile(entry)
                    magic = handle.read(8) if handle is not None else b""
                    if any(magic.startswith(h) for h in (
                        bytes.fromhex("feedface"), bytes.fromhex("cefaedfe"),
                        bytes.fromhex("feedfacf"), bytes.fromhex("cffaedfe"),
                        bytes.fromhex("cafebabe"), bytes.fromhex("bebafeca"),
                        bytes.fromhex("cafebabf"), bytes.fromhex("bfbafeca"),
                    )) or magic == b"!<arch>\\n":
                        native_candidates[name] = entry.size
    missing = sorted(required - seen)
    if missing:
        raise ValueError(f"Native archive missing required files: {missing}")
    for framework in ("CoMaps", "DuckDB"):
        info_path = f"{source}/ios/Frameworks/{framework}.xcframework/Info.plist"
        meta = arches.get(info_path)
        if meta is None:
            raise ValueError(f"iOS device metadata not found for {framework}")
        identifier, library_path = meta
        base = f"{source}/ios/Frameworks/{framework}.xcframework/{identifier}/{library_path}"
        expected = base + "/" + Path(library_path).stem if library_path.endswith(".framework") else base
        if expected not in native_candidates:
            matching = [name for name in native_candidates if f"/{framework}.xcframework/" in name]
            raise ValueError(f"No valid device Mach-O/archive for {framework}; expected {expected}; found {matching[:8]}")
    if len(arches) != 2:
        raise ValueError(f"Insufficient XCFramework iOS device slices: {arches}")
    print(f"PASS: streamed {count} TAR members and {total:,} unpacked bytes.")
    print("PASS: required pinned source metadata, GPS framework binaries, and offline map assets present.")
    print("PASS: CoMaps and DuckDB include real arm64 iOS device binaries.")
    print("No native compilation, extraction, or paid Codemagic action was started.")
    return {"files": count, "uncompressed": total}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--restore", type=Path, required=True)
    args = p.parse_args()
    audit(args.bundle, args.restore)
