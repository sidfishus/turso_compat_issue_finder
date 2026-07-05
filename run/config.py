from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    sqlite3_path: Path
    tursodb_path: Path
    temp_dir: Path

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            sqlite3_path=Path(os.environ.get("TURSO_COMPAT_SQLITE3", "sqlite3")),
            tursodb_path=Path(os.environ.get("TURSO_COMPAT_TURSODB", "tursodb")),
            temp_dir=Path(os.environ.get("TURSO_COMPAT_TEMP_DIR", "/tmp/turso_compat")),
        )
