# /// script
# requires-python = ">=3.10"
# dependencies = ["gdown==6.5.2"]
# ///
"""Download public supplements linked from the lab READMEs, preserving existing files.

Run with ``uv run scripts/download_supplements.py``. The inventory and resumable
download log are kept in the ignored downloads/supplements directory.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

import gdown
import requests

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "downloads" / "supplements"
MANIFEST = STATE / "manifest.json"
LOCK = threading.Lock()
NETWORK = threading.BoundedSemaphore(24)
CHUNK = 4 * 1024 * 1024


def log(message):
    with LOCK:
        print(message, flush=True)
        STATE.mkdir(parents=True, exist_ok=True)
        with (STATE / "download.log").open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")


def relative(path):
    return canonical(path).relative_to(ROOT).as_posix()


def canonical(path):
    value = str(path.resolve())
    if os.name == "nt" and value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def safe_path(path):
    target = canonical(ROOT / path)
    target.relative_to(ROOT)
    if target == ROOT or ".git" in target.relative_to(ROOT).parts:
        raise ValueError(f"Invalid supplement destination: {path}")
    # Windows needs extended paths for the long course/lab names and .part files.
    return Path("\\\\?\\" + str(target)) if os.name == "nt" else target


def save(manifest):
    STATE.mkdir(parents=True, exist_ok=True)
    temp = MANIFEST.with_suffix(".tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(MANIFEST)


def sources():
    tracked = subprocess.check_output(["git", "ls-files", "-z", "*README.md"], cwd=ROOT)
    result = []
    for name in tracked.decode("utf-8").split("\0"):
        if not name or name == "README.md":
            continue
        readme = ROOT / name
        for line_number, line in enumerate(readme.read_text(encoding="utf-8-sig").splitlines(), 1):
            match = re.search(r"https://drive\.google\.com/(?:drive/folders/|file/d/)([\w-]+)[^\s)]*", line)
            if not match:
                continue
            url = match.group(0)
            named = re.search(r"下载\s*`([^`]+)`", line)
            dest = readme.parent / named.group(1).rstrip("/") if named else readme.parent
            result.append({"id": match.group(1), "url": url,
                           "kind": "folder" if "/folders/" in url else "file",
                           "destination": relative(dest), "readme": name,
                           "line": line_number})
    return result


def discover(source):
    destination = safe_path(source["destination"])
    if source["kind"] == "file":
        entries = [{"id": source["id"], "path": relative(destination)}]
    else:
        files = gdown.download_folder(id=source["id"], output=str(destination),
                                      skip_download=True, quiet=True, use_cookies=False,
                                      timeout=(20, 60))
        entries = [{"id": item.id, "path": relative(Path(item.local_path))} for item in files]
    for entry in entries:
        target = safe_path(entry["path"])
        entry["source_id"] = source["id"]
        entry["existed_before"] = target.is_file()
        entry["status"] = "existing" if target.is_file() else "pending"
        if target.is_file():
            entry["bytes"] = target.stat().st_size
    return entries


def inventory(workers):
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(),
                "sources": sources(), "files": [], "discovery_errors": []}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(discover, source): source for source in manifest["sources"]}
        for future in as_completed(jobs):
            source = jobs[future]
            try:
                entries = future.result()
                manifest["files"].extend(entries)
                log(f"LIST {len(entries):5d} files: {source['destination']}")
            except Exception as error:
                manifest["discovery_errors"].append({"source": source, "error": str(error)})
                log(f"LIST FAILED {source['destination']}: {error}")
            save(manifest)
    normalize(manifest)
    save(manifest)
    return manifest


def normalize(manifest):
    unique = {}
    for entry in manifest["files"]:
        key = entry["path"].casefold()
        if key in unique and unique[key]["id"] != entry["id"]:
            unique[key].setdefault("alternate_ids", []).append(entry["id"])
            continue
        unique[key] = entry
    manifest["files"] = sorted(unique.values(), key=lambda entry: entry["path"])


def fetch(entry):
    target = safe_path(entry["path"])
    if target.is_file():
        return {"status": entry["status"] if entry["status"] == "downloaded" else "existing",
                "bytes": target.stat().st_size}
    target.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    url = "https://drive.usercontent.google.com/download"
    params = {"id": entry["id"], "export": "download", "confirm": "t"}
    cache = STATE / "ranges" / entry["id"]
    cache.mkdir(parents=True, exist_ok=True)
    # Fetch the first chunk and size together; small files need just one request.
    first = cache / "00000000.part"
    probe_end = 0 if first.exists() else CHUNK - 1
    with NETWORK, requests.get(url, params=params, headers={"Range": f"bytes=0-{probe_end}"},
                               stream=True, timeout=(20, 60)) as response:
        response.raise_for_status()
        content_range = response.headers.get("Content-Range", "")
        match = re.fullmatch(r"bytes 0-(\d+)/(\d+)", content_range)
        if response.status_code != 206 or not match:
            raise RuntimeError(f"Expected a ranged binary download, got {response.status_code} {content_range}")
        total = int(match.group(2))
        if int(match.group(1)) != min(probe_end, total - 1):
            raise RuntimeError("First download range has an unexpected length")
        if not first.exists():
            temp = first.with_suffix(".tmp")
            with temp.open("wb") as output:
                for block in response.iter_content(256 * 1024):
                    output.write(block)
            if temp.stat().st_size != min(CHUNK, total):
                raise RuntimeError("Incomplete first download range")
            temp.replace(first)
    count = (total + CHUNK - 1) // CHUNK

    def piece(number):
        start, end = number * CHUNK, min(total, (number + 1) * CHUNK) - 1
        part = cache / f"{number:08d}.part"
        if part.is_file() and part.stat().st_size == end - start + 1:
            return part
        temp = part.with_suffix(".tmp")
        for attempt in range(4):
            try:
                offset = temp.stat().st_size if temp.exists() else 0
                if offset == end - start + 1:
                    temp.replace(part)
                    return part
                if offset > end - start + 1:
                    raise RuntimeError("Cached range exceeds expected size")
                expected = f"bytes {start + offset}-{end}/{total}"
                with NETWORK, requests.get(url, params=params,
                        headers={"Range": f"bytes={start + offset}-{end}", "Accept-Encoding": "identity"},
                        stream=True, timeout=(20, 90)) as response:
                    response.raise_for_status()
                    if response.status_code != 206 or response.headers.get("Content-Range") != expected:
                        raise RuntimeError(f"Invalid download range: {response.headers.get('Content-Range')}")
                    with temp.open("ab") as output:
                        for block in response.iter_content(256 * 1024):
                            output.write(block)
                if temp.stat().st_size != end - start + 1:
                    raise RuntimeError("Incomplete download range")
                temp.replace(part)
                return part
            except (requests.RequestException, OSError, RuntimeError):
                if attempt == 3:
                    raise
                time.sleep(1 + attempt)

    with ThreadPoolExecutor(max_workers=min(8, max(1, count))) as pool:
        parts = list(pool.map(piece, range(count)))
    assembled = cache / "complete.part"
    with assembled.open("wb") as output:
        for part in parts:
            with part.open("rb") as source:
                while block := source.read(1024 * 1024):
                    output.write(block)
                    hasher.update(block)
    if assembled.stat().st_size != total:
        raise RuntimeError("Assembled file size does not match Google Drive")
    if target.exists():
        raise RuntimeError("Destination appeared during download; existing file was preserved")
    assembled.replace(target)
    for part in parts:
        part.unlink()
    if not target.is_file():
        raise RuntimeError("Download returned without a completed file")
    return {"status": "downloaded", "bytes": target.stat().st_size,
            "sha256": hasher.hexdigest()}


def fetch_retried(entry):
    for attempt in range(4):
        try:
            return fetch(entry)
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 + attempt)


def download(manifest, workers):
    for entry in manifest["files"]:
        target = safe_path(entry["path"])
        if target.is_file():
            entry["bytes"] = target.stat().st_size
            if entry["status"] in {"pending", "failed"}:
                entry["status"] = "existing" if entry["existed_before"] else "downloaded"
                entry.pop("error", None)
    save(manifest)
    pending = [entry for entry in manifest["files"] if not safe_path(entry["path"]).is_file()]
    # Start large weights/embeddings early, so they overlap with the image queue.
    heavy = (".h5", ".mat", ".bin", ".npy", ".gz", ".data-00000-of-00001")
    pending.sort(key=lambda entry: (not (entry["path"].endswith(heavy) or
                                        "glove.6B." in entry["path"]), entry["path"]))
    log(f"DOWNLOAD {len(pending)} missing; {len(manifest['files']) - len(pending)} existing files skipped")
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(fetch_retried, entry): entry for entry in pending}
        for future in as_completed(jobs):
            entry = jobs[future]
            try:
                entry.update(future.result())
                entry.pop("error", None)
                completed += 1
                if completed % 25 == 0 or entry["bytes"] > 50 * 1048576:
                    log(f"DONE {completed}/{len(pending)} ({entry['bytes'] / 1048576:.1f} MiB): {entry['path']}")
            except Exception as error:
                entry.update(status="failed", error=str(error))
                log(f"FAILED {entry['path']}: {error}")
            save(manifest)
    return manifest


def summary(manifest):
    present = [entry for entry in manifest["files"] if safe_path(entry["path"]).is_file()]
    missing = len(manifest["files"]) - len(present)
    size = sum(safe_path(entry["path"]).stat().st_size for entry in present)
    log(f"SUMMARY {len(present)}/{len(manifest['files'])} files present; {size / 1073741824:.3f} GiB; "
        f"{missing} missing; {len(manifest['discovery_errors'])} failed source listings")
    return 1 if missing or manifest["discovery_errors"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Rebuild the cached source inventory")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error("--workers must be between 1 and 16")
    manifest = (json.loads(MANIFEST.read_text(encoding="utf-8"))
                if MANIFEST.exists() and not args.refresh else inventory(args.workers))
    normalize(manifest)
    save(manifest)
    if not args.inventory_only:
        download(manifest, args.workers)
    return summary(manifest)


if __name__ == "__main__":
    raise SystemExit(main())
