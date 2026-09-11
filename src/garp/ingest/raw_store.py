"""Content-addressed immutable storage for raw downloads.

Per SPEC.md principle #5: raw files are cached under `data/raw/<source>/` by
the sha256 of their payload and are never mutated in place. Every write is
paired with a JSON sidecar carrying the fetch metadata (source, URL,
retrieval timestamp, hash) so a raw file's provenance is always recoverable
without re-parsing logs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from garp.logging import get_logger, hash_payload, log_fetch

logger = get_logger(__name__)


@dataclass(frozen=True)
class CachedResponse:
    """A raw payload plus the metadata recorded alongside it."""

    payload: bytes
    sha256: str
    path: Path
    sidecar_path: Path
    from_cache: bool


def _sidecar_path(payload_path: Path) -> Path:
    return payload_path.with_suffix(payload_path.suffix + ".meta.json")


def store(
    *,
    raw_dir: Path,
    source: str,
    url: str,
    payload: bytes,
    suffix: str = ".json",
    extra: dict[str, Any] | None = None,
) -> CachedResponse:
    """Write `payload` to `raw_dir/source/<sha256><suffix>`, idempotently.

    If a file with the same content hash already exists, it is left
    untouched (raw files are immutable) and `from_cache=True` is returned.
    """
    source_dir = raw_dir / source
    source_dir.mkdir(parents=True, exist_ok=True)

    digest = hash_payload(payload)
    payload_path = source_dir / f"{digest}{suffix}"
    sidecar_path = _sidecar_path(payload_path)

    if payload_path.is_file():
        logger.debug("raw_cache_hit", source=source, url=url, payload_sha256=digest)
        return CachedResponse(
            payload=payload_path.read_bytes(),
            sha256=digest,
            path=payload_path,
            sidecar_path=sidecar_path,
            from_cache=True,
        )

    retrieved_at = datetime.now(UTC)
    log_fetch(
        logger, source=source, url=url, payload=payload, retrieved_at=retrieved_at, **(extra or {})
    )

    payload_path.write_bytes(payload)
    sidecar_path.write_text(
        json.dumps(
            {
                "source": source,
                "url": url,
                "retrieved_at": retrieved_at.isoformat(),
                "sha256": digest,
                "bytes": len(payload),
                **(extra or {}),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    return CachedResponse(
        payload=payload,
        sha256=digest,
        path=payload_path,
        sidecar_path=sidecar_path,
        from_cache=False,
    )


def sidecar_metadata(response: CachedResponse) -> dict[str, Any]:
    """Read back a cached response's sidecar metadata as a plain dict."""
    result: dict[str, Any] = json.loads(response.sidecar_path.read_text())
    return result
