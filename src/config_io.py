"""Read and write .env preserving comments, blank lines, and unknown keys."""

from __future__ import annotations

from pathlib import Path

from src.config_schema import ENV_KEYS


def read_env(path: Path) -> dict[str, str]:
    """Return {KEY: value} for every recognised KEY=value line. Comments/blanks dropped."""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        kv = _parse_kv(line)
        if kv is not None:
            result[kv[0]] = kv[1]
    return result


def write_env(path: Path, values: dict[str, str]) -> None:
    """Write `values` to `path`, preserving existing comments and unknown lines.

    For known keys (in ENV_KEYS) present in `values`:
    - if the line exists in the file, replace with `KEY=value`
    - otherwise append at the end
    Unknown lines (comments, blanks, unrecognised KV) pass through untouched.
    """
    existing_lines = path.read_text().splitlines() if path.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in existing_lines:
        kv = _parse_kv(line)
        if kv is not None and kv[0] in values:
            out.append(f"{kv[0]}={values[kv[0]]}")
            seen.add(kv[0])
        else:
            out.append(line)
    for key in ENV_KEYS:
        if key in values and key not in seen:
            out.append(f"{key}={values[key]}")
    path.write_text("\n".join(out) + "\n")


def _parse_kv(line: str) -> tuple[str, str] | None:
    """Parse 'KEY=value'. KEY must match /[A-Z_][A-Z0-9_]*/ to be recognised."""
    s = line.lstrip()
    if not s or s.startswith("#") or "=" not in s:
        return None
    key, _, value = s.partition("=")
    if not key:
        return None
    if not (key[0].isupper() or key[0] == "_"):
        return None
    if not all(c.isupper() or c.isdigit() or c == "_" for c in key):
        return None
    return key, value.rstrip()
