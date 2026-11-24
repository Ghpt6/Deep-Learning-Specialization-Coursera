"""Verify and restore versioned course assets from GitHub Release volumes.

Only the Python standard library is required. Valid local assets never cause a
network request. Interrupted downloads are resumed and every volume, archive,
and restored file is checked against the committed SHA-256 manifest.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "supplements" / "manifest.json"
BLOCK = 1024 * 1024


def safe_path(root, name):
    parts = PurePosixPath(name)
    if not name or parts.is_absolute() or ".." in parts.parts or "\\" in name or ":" in name:
        raise ValueError(f"Unsafe asset path: {name}")
    base = os.path.realpath(root).removeprefix("\\\\?\\")
    full = os.path.realpath(Path(base) / name).removeprefix("\\\\?\\")
    if os.path.normcase(os.path.commonpath([base, full])) != os.path.normcase(base) or full == base:
        raise ValueError(f"Asset path escapes destination: {name}")
    return Path("\\\\?\\" + full) if os.name == "nt" else Path(full)


def sha256(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(BLOCK):
            hasher.update(data)
    return hasher.hexdigest()


def valid_file(path, item):
    return path.is_file() and path.stat().st_size == item["size"] and sha256(path) == item["sha256"]


def load_manifest(path):
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or manifest["archive"]["format"] != "tar.gz":
        raise ValueError("Unsupported supplemental asset manifest")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", manifest["release_tag"]):
        raise ValueError("Invalid asset release tag")
    names = set()
    for item in manifest["files"]:
        safe_path(ROOT, item["path"])
        key = item["path"].casefold()
        if key in names:
            raise ValueError(f"Duplicate asset path: {item['path']}")
        names.add(key)
        if item["course"] not in range(1, 6):
            raise ValueError("Invalid course in manifest")
    for item in [manifest["archive"], *manifest["archive"]["parts"], *manifest["files"]]:
        if not isinstance(item["size"], int) or item["size"] < 0 or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("Invalid size or checksum in manifest")
    if sum(part["size"] for part in manifest["archive"]["parts"]) != manifest["archive"]["size"]:
        raise ValueError("Archive volume sizes do not add up")
    part_names = [part["name"] for part in manifest["archive"]["parts"]]
    if len(part_names) != len(set(part_names)) or not part_names:
        raise ValueError("Invalid archive volume list")
    for name in part_names:
        if PurePosixPath(name).name != name:
            raise ValueError("Archive volume names must be plain filenames")
        safe_path(ROOT, name)
    return manifest


def download_part(item, cache, opener=None, retries=3, delay=None):
    opener = opener or urllib.request.urlopen
    delay = delay or time.sleep
    destination = safe_path(cache, item["name"])
    if valid_file(destination, item):
        return destination
    temporary = destination.with_name(destination.name + ".part")
    cache.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries + 1):
        try:
            offset = temporary.stat().st_size if temporary.exists() else 0
            if offset >= item["size"]:
                if valid_file(temporary, item):
                    os.replace(temporary, destination)
                    return destination
                temporary.unlink()
                offset = 0
            headers = {"User-Agent": "dls-course-setup/1", "Accept-Encoding": "identity"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(item["url"], headers=headers)
            with opener(request, timeout=60) as response:
                if response.status == 206:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if not match or tuple(map(int, match.groups())) != (offset, item["size"] - 1, item["size"]):
                        raise ValueError("Server returned an invalid download range")
                elif response.status == 200:
                    offset = 0  # Servers may ignore Range; restart rather than append twice.
                else:
                    raise ValueError(f"Unexpected download status: {response.status}")
                length = response.headers.get("Content-Length")
                if length is not None and int(length) != item["size"] - offset:
                    raise ValueError("Server returned an unexpected download size")
                print(f"Downloading {item['name']} from {offset / BLOCK:.1f} MiB", flush=True)
                last = time.monotonic()
                with temporary.open("ab" if offset else "wb") as output:
                    received = offset
                    while data := response.read(BLOCK):
                        received += len(data)
                        if received > item["size"]:
                            raise ValueError("Download exceeds manifest size")
                        output.write(data)
                        if time.monotonic() - last >= 30:
                            print(f"  {received / BLOCK:.1f}/{item['size'] / BLOCK:.1f} MiB", flush=True)
                            last = time.monotonic()
            if not valid_file(temporary, item):
                if temporary.stat().st_size == item["size"]:
                    temporary.unlink()  # Bad content must not be reused as a resume prefix.
                raise ValueError("Downloaded asset failed size/SHA-256 verification")
            os.replace(temporary, destination)
            return destination
        except (OSError, ValueError, urllib.error.URLError, socket.timeout, http.client.HTTPException) as error:
            if attempt == retries:
                raise RuntimeError(f"Could not download {item['name']}: {error}. Rerun setup to resume.") from error
            delay(min(2 ** attempt, 8))
    raise AssertionError("Unreachable")


class JoinedParts(io.RawIOBase):
    def __init__(self, paths):
        super().__init__()
        self.paths = iter(paths)
        self.current = None

    def readable(self):
        return True

    def readinto(self, buffer):
        while True:
            if self.current is None:
                path = next(self.paths, None)
                if path is None:
                    return 0
                self.current = path.open("rb")
            size = self.current.readinto(buffer)
            if size:
                return size
            self.current.close()
            self.current = None

    def close(self):
        if self.current is not None:
            self.current.close()
        super().close()


def verify_archive(paths, archive):
    hasher = hashlib.sha256()
    size = 0
    for path in paths:
        with path.open("rb") as stream:
            while data := stream.read(BLOCK):
                size += len(data)
                hasher.update(data)
    if size != archive["size"] or hasher.hexdigest() != archive["sha256"]:
        raise RuntimeError("Combined archive failed SHA-256 verification")


def restore_archive(root, manifest, paths, needed, cache):
    expected = {item["path"]: item for item in manifest["files"]}
    seen, restored = set(), 0
    with JoinedParts(paths) as raw, io.BufferedReader(raw) as stream:
        with tarfile.open(fileobj=stream, mode="r|gz") as archive:
            for member in archive:
                target = safe_path(root, member.name)
                if member.name not in expected or member.name in seen or not member.isfile():
                    raise ValueError(f"Unexpected archive member: {member.name}")
                item = expected[member.name]
                if member.size != item["size"]:
                    raise ValueError(f"Wrong archived file size: {member.name}")
                seen.add(member.name)
                if member.name not in needed:
                    continue
                handle, temporary_name = tempfile.mkstemp(prefix="extract-", dir=cache)
                temporary = Path(temporary_name)
                try:
                    with os.fdopen(handle, "wb") as output, archive.extractfile(member) as source:
                        shutil.copyfileobj(source, output, BLOCK)
                    if not valid_file(temporary, item):
                        raise RuntimeError(f"Restored file failed checksum: {member.name}")
                    if valid_file(target, item):
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        if not target.is_file():
                            raise RuntimeError(f"Expected a file but found a directory: {target}")
                        backup = safe_path(cache / "backups", member.name + "." + sha256(target)[:16])
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(target, backup)
                        print(f"Preserved mismatched local file in {backup}", flush=True)
                    os.replace(temporary, target)
                    restored += 1
                finally:
                    if temporary.exists():
                        temporary.unlink()
    if seen != set(expected):
        raise RuntimeError("Archive is missing files listed in its manifest")
    return restored


def ensure_assets(root=ROOT, manifest_path=MANIFEST, courses=None, check_only=False, cache=None):
    manifest = load_manifest(manifest_path)
    selected = [item for item in manifest["files"] if not courses or item["course"] in courses]
    needed = {item["path"] for item in selected if not valid_file(safe_path(root, item["path"]), item)}
    if not needed:
        print(f"Supplemental assets: {len(selected)} files verified; no download needed.", flush=True)
        return 0
    if check_only:
        raise RuntimeError(f"{len(needed)} supplemental files are missing or invalid. Run setup without --check-only.")
    cache = cache or safe_path(root, "downloads/supplements/releases/" + manifest["release_tag"])
    cache.mkdir(parents=True, exist_ok=True)
    print(f"Supplemental assets: {len(needed)} missing/invalid; {len(selected) - len(needed)} valid files preserved.", flush=True)
    with ThreadPoolExecutor(max_workers=min(4, len(manifest["archive"]["parts"]))) as pool:
        paths = list(pool.map(lambda part: download_part(part, cache), manifest["archive"]["parts"]))
    verify_archive(paths, manifest["archive"])
    restored = restore_archive(root, manifest, paths, needed, cache)
    print(f"Supplemental assets: restored and verified {restored} files.", flush=True)
    return restored


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course", type=int, nargs="+", choices=range(1, 6))
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        ensure_assets(courses=args.course, check_only=args.check_only)
    except (OSError, ValueError, RuntimeError, tarfile.TarError) as error:
        parser.exit(1, f"Supplemental assets: {error}\n")


if __name__ == "__main__":
    main()
