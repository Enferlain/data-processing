from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def public_path(path: Path) -> str:
    """Return a path label safe for ordinary command output."""
    return path.name


def render_result(result: dict[str, Any], *, as_json: bool) -> str:
    if as_json:
        return json.dumps(result, ensure_ascii=False, sort_keys=True)
    return "\n".join(f"{key}: {_human_value(value)}" for key, value in result.items())


def _human_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def bounded_error(
    error: BaseException, *, private_paths: tuple[Path, ...] = (), limit: int = 500
) -> str:
    message = " ".join(str(error).splitlines()).strip() or type(error).__name__
    for path in private_paths:
        candidates = {str(path), str(path.absolute())}
        with_resolved = path.resolve(strict=False)
        candidates.add(str(with_resolved))
        for candidate in sorted(candidates, key=len, reverse=True):
            message = message.replace(candidate, public_path(path))
    if len(message) > limit:
        return f"{message[: limit - 1]}…"
    return message
