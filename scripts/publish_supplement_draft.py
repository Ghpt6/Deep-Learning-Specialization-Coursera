"""Build-task support: restore the original 39 files and upload a verified draft.

Uses GITHUB_TOKEN only for this repository's GitHub API. This never publishes a
release; publication happens after the installer and the draft have been checked.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile

import requests

from supplement_assets import JoinedParts, safe_path, sha256, valid_file, verify_archive

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "supplements/manifest.json"
BLOCK = 1024 * 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["seed", "upload"])
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    repository = os.environ.get("GITHUB_REPOSITORY", manifest["repository"])
    if repository != manifest["repository"]:
        raise RuntimeError("Release repository differs from the asset manifest")
    base = "https://api.github.com/repos/" + repository
    headers = {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "Accept": "application/vnd.github+json"}

    def api(method, url, **kwargs):
        response = requests.request(method, url, headers=headers, timeout=(30, 600), **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    release = next(item for item in api("GET", base + "/releases") if item["tag_name"] == manifest["release_tag"])
    if not release["draft"]:
        raise RuntimeError("Refusing to alter an already published release")
    listing = api("GET", base + f"/releases/{release['id']}/assets")
    if args.operation == "seed":
        seed = next(item for item in listing if item["name"] == "existing-assets-v1.tar.gz")
        response = requests.get(seed["url"], headers={**headers, "Accept": "application/octet-stream"}, timeout=(30, 120))
        response.raise_for_status()
        if "sha256:" + hashlib.sha256(response.content).hexdigest() != seed["digest"]:
            raise RuntimeError("Seed asset checksum mismatch")
        expected = {item["path"]: item for item in manifest["files"]}
        restored = set()
        with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
            for member in archive:
                if not member.isfile() or member.name not in expected or member.name in restored:
                    raise RuntimeError("Unexpected seed archive member")
                target = safe_path(ROOT, member.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                data = archive.extractfile(member).read()
                item = expected[member.name]
                if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise RuntimeError("Seed file checksum mismatch")
                target.write_bytes(data)
                restored.add(member.name)
        if len(restored) != 39:
            raise RuntimeError("Expected exactly 39 original files")
        print("Restored and verified the 39 original files.", flush=True)
        return

    directory = ROOT / "downloads/supplements/release" / manifest["release_tag"]
    paths = [directory / part["name"] for part in manifest["archive"]["parts"]]
    verify_archive(paths, manifest["archive"])
    expected = {item["path"]: item for item in manifest["files"]}
    seen = set()
    with JoinedParts(paths) as raw, io.BufferedReader(raw) as stream:
        with tarfile.open(fileobj=stream, mode="r|gz") as archive:
            for member in archive:
                if member.name not in expected or member.name in seen or not member.isfile():
                    raise RuntimeError("Unexpected release archive member")
                item = expected[member.name]
                if member.size != item["size"]:
                    raise RuntimeError("Incorrect archived file size")
                digest = hashlib.sha256()
                with archive.extractfile(member) as source:
                    while data := source.read(BLOCK):
                        digest.update(data)
                if digest.hexdigest() != item["sha256"]:
                    raise RuntimeError("Archived file checksum mismatch")
                seen.add(member.name)
    if len(seen) != 2758 or seen != set(expected):
        raise RuntimeError("Incomplete release archive")
    print("All 2,758 archived files verified.", flush=True)
    items = [dict(part) for part in manifest["archive"]["parts"]]
    for name in ("manifest.json", "SHA256SUMS"):
        path = directory / name
        items.append({"name": name, "size": path.stat().st_size, "sha256": sha256(path)})
    existing = {item["name"]: item for item in listing}

    def upload(item):
        path = directory / item["name"]
        if not valid_file(path, item):
            raise RuntimeError("Local upload checksum mismatch")
        previous = existing.get(item["name"])
        if previous:
            if previous.get("digest") == "sha256:" + item["sha256"] and previous["size"] == item["size"]:
                return
            # This workflow owns only named assets in the unpublished supplement draft.
            api("DELETE", base + "/releases/assets/" + str(previous["id"]))
        endpoint = release["upload_url"].split("{")[0]
        if not endpoint.startswith("https://uploads.github.com/repos/" + repository + "/"):
            raise RuntimeError("Unexpected GitHub upload endpoint")
        with path.open("rb") as body:
            response = requests.post(endpoint, params={"name": item["name"]},
                headers={**headers, "Content-Type": "application/octet-stream", "Content-Length": str(item["size"])},
                data=body, timeout=(30, 600))
        response.raise_for_status()
        result = response.json()
        if result["size"] != item["size"] or result.get("digest") != "sha256:" + item["sha256"]:
            raise RuntimeError("GitHub upload digest mismatch")
        print("Uploaded and verified:", item["name"], flush=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(upload, items))
    body = ("包含全部 2,758 个补充文件（含原有 39 个），覆盖 22 个实验目录。"
            f"一个无损 tar.gz 资料包分为 {len(paths)} 卷，每卷不超过 256 MiB。\n\n"
            "运行仓库中的 setup.ps1 或 setup.sh 即可自动检测、下载、校验和还原。"
            "已有且通过 SHA-256 校验的文件会保留，下载支持断点续传。\n\n"
            "manifest.json 记录所有文件与分卷的大小和 SHA-256；SHA256SUMS 可用于手工核对。"
            "资料来源保留在各实验 README 中。")
    api("PATCH", base + "/releases/" + str(release["id"]),
        json={"tag_name": manifest["release_tag"], "name": "Course supplements v1", "body": body, "draft": True})
    print("Draft assets complete; release remains unpublished.", flush=True)


if __name__ == "__main__":
    main()
