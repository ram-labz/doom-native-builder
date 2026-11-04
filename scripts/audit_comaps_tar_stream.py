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
    native_binary = set()
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
                    arches[name] = True
            for framework in ("CoMaps", "DuckDB"):
                marker = f"/{framework}.xcframework/ios-arm64/{framework}.framework/{framework}"
                if name.startswith(source + "/ios/Frameworks/") and name.endswith(marker):
                    if entry.size < 8192:
                        raise ValueError(f"Native device binary is too small: {name}")
                    native_binary.add(framework)
    missing = sorted(required - seen)
    if missing:
        raise ValueError(f"Native archive missing required files: {missing}")
    if set(native_binary) != {"CoMaps", "DuckDB"}:
        raise ValueError(f"Native device binaries not detected: {native_binary}")
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
