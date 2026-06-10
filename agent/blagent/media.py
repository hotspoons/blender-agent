# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Per-session media library, ported from Foyer Studio's
``foyer-agent/src/media.rs``.

Tool-produced images are stamped with a short id (``i1``, ``i2``, ...)
so the model can reference them later, the UI can render them in the
artifacts panel, and vision-capable models can get them fed back into
context on the following round.
"""

__all__ = (
    "MediaItem",
    "MediaLibrary",
)

import base64
import dataclasses
import os
import time


@dataclasses.dataclass
class MediaItem:
    media_id: str
    mime: str
    label: str
    path: str
    created: float

    def as_public(self) -> dict[str, object]:
        return {
            "id": self.media_id,
            "mime": self.mime,
            "label": self.label,
            "created": self.created,
        }


class MediaLibrary:
    """
    Disk-backed short-id registry for one session's media.
    """

    def __init__(self, directory: str) -> None:
        self._dir = directory
        self._items: dict[str, MediaItem] = {}
        self._counter = 0
        self._load_existing()

    def _load_existing(self) -> None:
        if not os.path.isdir(self._dir):
            return
        for filename in sorted(os.listdir(self._dir)):
            media_id, _sep, rest = filename.partition(".")
            if not media_id.startswith("i"):
                continue
            try:
                index = int(media_id[1:])
            except ValueError:
                continue
            path = os.path.join(self._dir, filename)
            self._items[media_id] = MediaItem(
                media_id=media_id,
                mime="image/{:s}".format(rest or "png"),
                label="",
                path=path,
                created=os.path.getmtime(path),
            )
            self._counter = max(self._counter, index)

    def register_base64(self, data_b64: str, mime: str, label: str) -> str:
        """
        Store a base64 payload and return its short id.
        """
        return self.register_bytes(base64.b64decode(data_b64), mime=mime, label=label)

    def register_bytes(self, data: bytes, mime: str, label: str) -> str:
        self._counter += 1
        media_id = "i{:d}".format(self._counter)
        ext = mime.rsplit("/", 1)[-1] or "bin"
        os.makedirs(self._dir, exist_ok=True)
        path = os.path.join(self._dir, "{:s}.{:s}".format(media_id, ext))
        with open(path, "wb") as fh:
            fh.write(data)
        self._items[media_id] = MediaItem(
            media_id=media_id,
            mime=mime,
            label=label,
            path=path,
            created=time.time(),
        )
        return media_id

    def get(self, media_id: str) -> MediaItem | None:
        return self._items.get(media_id)

    def read_base64(self, media_id: str) -> str | None:
        item = self._items.get(media_id)
        if item is None or not os.path.isfile(item.path):
            return None
        with open(item.path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")

    def list_public(self) -> list[dict[str, object]]:
        return [item.as_public() for item in self._items.values()]
