import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_id(namespace: str, *parts: str) -> str:
    payload = "\0".join((namespace, *parts)).encode("utf-8")
    return f"{namespace}-{hashlib.sha256(payload).hexdigest()[:24]}"


def stable_fingerprint(data: Any) -> str:
    encoded = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
