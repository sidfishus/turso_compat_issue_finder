from __future__ import annotations

import hashlib
import shutil
import tarfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_archive(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
        return
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            tf.extractall(dest)
        return
    raise RuntimeError(f"unsupported archive format: {archive}")


def download_file(
    url: str,
    dest: Path,
    *,
    expected_sha256: str | None = None,
    force: bool = False,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        if expected_sha256 is None or sha256(dest) == expected_sha256:
            return dest
        dest.unlink()

    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"downloading {url}")
    urlretrieve(url, tmp)
    if expected_sha256 is not None and sha256(tmp) != expected_sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"download failed SHA256 check: {dest.name}")
    tmp.replace(dest)
    return dest


def clear_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
