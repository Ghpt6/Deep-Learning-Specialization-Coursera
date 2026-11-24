"""Build a reproducible tar.gz containing every file in the verified inventory.

uv run --no-project python scripts/build_supplement_release.py
Outputs stay in downloads/supplements/release; only the small manifest goes in Git.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import tarfile

from supplement_assets import safe_path

ROOT = Path(__file__).resolve().parents[1]
BLOCK = 4 * 1024 * 1024


def local(path):
    return safe_path(ROOT, path)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(BLOCK):
            result.update(data)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="supplements-v1")
    parser.add_argument("--repository", default="Ghpt6/Deep-Learning-Specialization-Coursera")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.tag):
        parser.error("Invalid release tag")
    source = ROOT / "downloads/supplements/validation.json"
    if source.exists():
        inventory = json.loads(source.read_text(encoding="utf-8"))
    else:
        published = json.loads((ROOT / "supplements/manifest.json").read_text(encoding="utf-8"))
        inventory = [dict(item, bytes=item["size"], status="ok") for item in published["files"]]
    entries = sorted(inventory, key=lambda item: item["path"])
    if len(entries) != 2758 or any(item["status"] != "ok" for item in entries):
        raise RuntimeError("Expected all 2,758 validated supplemental files")
    output = ROOT / "downloads/supplements/release" / args.tag
    output.mkdir(parents=True, exist_ok=True)
    name = f"dls-{args.tag}.tar.gz"
    archive = output / name
    temporary = archive.with_suffix(".tmp")
    files = []
    with temporary.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as tar:
            for number, item in enumerate(entries, 1):
                path = local(item["path"])
                if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
                    raise RuntimeError(f"Source changed since validation: {item['path']}")
                info = tarfile.TarInfo(item["path"])
                info.size, info.mode, info.mtime = item["bytes"], 0o644, 0
                with path.open("rb") as stream:
                    tar.addfile(info, stream)
                files.append({"path": item["path"], "size": item["bytes"], "sha256": item["sha256"],
                              "course": int(item["path"].split()[1])})
                if number % 250 == 0:
                    print(f"Packed {number}/{len(entries)} files", flush=True)
    temporary.replace(archive)
    size = archive.stat().st_size
    archive_hash = digest(archive)
    parts = []
    if size < 2 * 1024**3:
        parts.append({"name": name, "size": size, "sha256": archive_hash})
    else:
        maximum = 256 * 1024**2
        with archive.open("rb") as stream:
            number = 1
            while True:
                data = stream.read(BLOCK)
                if not data:
                    break
                part = output / f"{name}.{number:03d}"
                hasher, written = hashlib.sha256(), 0
                with part.open("wb") as destination:
                    while data:
                        destination.write(data)
                        hasher.update(data)
                        written += len(data)
                        if written == maximum:
                            break
                        data = stream.read(min(BLOCK, maximum - written))
                parts.append({"name": part.name, "size": written, "sha256": hasher.hexdigest()})
                number += 1
    base = f"https://github.com/{args.repository}/releases/download/{args.tag}/"
    for part in parts:
        part["url"] = base + part["name"]
    manifest = {"version": 1, "release_tag": args.tag, "repository": args.repository,
                "archive": {"name": name, "format": "tar.gz", "size": size, "sha256": archive_hash, "parts": parts},
                "files": files}
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    (output / "manifest.json").write_text(text, encoding="utf-8")
    metadata = ROOT / "supplements"
    metadata.mkdir(exist_ok=True)
    (metadata / "manifest.json").write_text(text, encoding="utf-8")
    (output / "SHA256SUMS").write_text("".join(f"{part['sha256']}  {part['name']}\n" for part in parts), encoding="utf-8")
    print(json.dumps({"files": len(files), "original_bytes": sum(item["size"] for item in files),
                      "compressed_bytes": size, "volumes": len(parts), "directory": str(output)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
