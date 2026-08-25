from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(frozen=True)
class SSEEvent:
    event: str
    data: str
    event_id: str | None = None


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[SSEEvent]:
    event_type = "message"
    event_id: str | None = None
    data: list[str] = []

    async for raw_line in lines:
        line = raw_line.rstrip("\r")
        if not line:
            if data:
                yield SSEEvent(event_type, "\n".join(data), event_id)
            event_type, event_id, data = "message", None, []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_type = value
        elif field == "data":
            data.append(value)
        elif field == "id" and "\x00" not in value:
            event_id = value

    if data:
        yield SSEEvent(event_type, "\n".join(data), event_id)
