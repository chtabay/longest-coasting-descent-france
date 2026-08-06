"""Download/verify the compact Phase 1 inputs declared in the manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from urllib.error import URLError
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/phase1_manifest.json")
    parser.add_argument("--cache", default=".cache/phase1")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    for item in manifest["files"]:
        target = cache / item["filename"]
        if not target.exists() and args.download:
            try:
                with urllib.request.urlopen(item["url"], timeout=120) as response:
                    target.write_bytes(response.read())
            except (OSError, URLError) as error:
                print(f"UNAVAILABLE {item['id']}: {error}")
        if not target.exists():
            print(f"MISSING {item['id']}: {target}")
            continue
        actual = sha256(target)
        expected = item.get("sha256")
        if expected and actual != expected:
            raise SystemExit(f"CHECKSUM MISMATCH {item['id']}: {actual}")
        print(f"OK {item['id']} bytes={target.stat().st_size} sha256={actual}")


if __name__ == "__main__":
    main()
