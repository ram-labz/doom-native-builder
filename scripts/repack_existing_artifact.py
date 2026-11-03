#!/usr/bin/env python3
"""Repack the successful iOS native artifact without rebuilding CoMaps.

Reads the existing GitHub Actions artifact ZIP and streams its inner tar.gz
into a smaller tar.gz. Never extracts the huge native tree to disk.
"""
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from urllib.parse import urlparse
import zipfile

class GitHubArtifactRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub API redirects to a signed artifact URL on another host.

    Do not forward the GitHub bearer token to artifact storage; the
    pre-signed download URL authenticates itself.
    """
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urlparse(newurl).hostname != urlparse(req.full_url).hostname:
            for key in list(redirected.headers):
                if key.lower() == "authorization":
                    del redirected.headers[key]
            for key in list(redirected.unredirected_hdrs):
                if key.lower() == "authorization":
                    del redirected.unredirected_hdrs[key]
        return redirected


RUN_ID = "41710765023"
ARTIFACT_ID = "13274835129"
API = f"https://api.github.com/repos/ram-labz/doom-native-builder/actions/artifacts/{ARTIFACT_ID}/zip"
ROOT = ".native_build/agus_maps_flutter/"
SKIP_PARTS = {
    ".dart_tool", ".build", "build", "DerivedData", "Pods",
    ".gradle", ".idea", ".vs", "node_modules", "CMakeFiles",
}
SKIP_PREFIXES = (
    ROOT + "example/",
    ROOT + "widgetbook/",
    ROOT + "tool/skin_generator_tool/",
    ROOT + "packages/agus_design/example/",
    ROOT + "thirdparty/comaps/.git/",
    ROOT + "thirdparty/duckdb/.git/",
)
# SwiftPM still requires plugin sources, headers, and ThirdParty links.
def keep(name):
    n = name.removeprefix("./").rstrip("/")
    if not n:
        return False
    if n.startswith("assets/"):
        return True
    if not n.startswith(ROOT):
        return False
    if any(n.startswith(p) for p in SKIP_PREFIXES):
        return False
    relative = n[len(ROOT):]
    if any(p in SKIP_PARTS for p in relative.split("/")):
        return False
    return True

def main():
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise SystemExit("Missing GH_TOKEN")
    out = Path(os.environ.get("OUTPUT", "/tmp/doom-ios-native-slim.tar.gz"))
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "artifact.zip"
        req = urllib.request.Request(API, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "doom-native-repack",
        })
        print("Downloading existing successful build artifact; NO compilation.", flush=True)
        opener = urllib.request.build_opener(GitHubArtifactRedirect())
        with opener.open(req, timeout=120) as response, zip_path.open("wb") as f:
            shutil.copyfileobj(response, f, 4 * 1024 * 1024)
        print(f"Downloaded ZIP: {zip_path.stat().st_size:,} bytes", flush=True)
        with zipfile.ZipFile(zip_path) as z:
            names = [n for n in z.namelist() if n.endswith(".tar.gz")]
            if len(names) != 1:
                raise RuntimeError(f"Expected one native tar.gz; found {names}")
            counts = {}
            with z.open(names[0]) as inner, tarfile.open(fileobj=inner, mode="r|gz") as source, tarfile.open(out, mode="w:gz", compresslevel=3) as target:
                for member in source:
                    n = member.name.removeprefix("./")
                    if not keep(member.name):
                        continue
                    category = n.split("/")[0] if n.startswith("assets/") else (n[len(ROOT):].split("/")[0] or "root")
                    if member.isfile():
                        counts[category] = counts.get(category, 0) + member.size
                        f = source.extractfile(member)
                        if f is None:
                            raise RuntimeError(f"Cannot read {n}")
                        target.addfile(member, f)
                    else:
                        target.addfile(member)
            print("Retained categories, uncompressed bytes:", flush=True)
            for key, size in sorted(counts.items(), key=lambda x: -x[1]):
                print(f"  {key}: {size:,}", flush=True)
        digest = hashlib.file_digest(out.open("rb"), "sha256").hexdigest()
        sha = out.with_suffix(out.suffix + ".sha256")
        sha.write_text(f"{digest}  {out.name}\n")
        print(f"SLIM_BYTES={out.stat().st_size}", flush=True)
        print(f"SLIM_SHA256={digest}", flush=True)
        print(f"OUTPUT={out}", flush=True)
        if out.stat().st_size >= 7 * 1024**3:
            raise RuntimeError("Repack still exceeds 7 GiB; stop before upload and inspect retained categories.")

if __name__ == "__main__":
    main()
