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

The library's directory doubles as the session's media-IO jail (the
``media_io`` tool's working folder): user attachments of any type and
Blender exports live here under their own (collision-suffixed) filenames,
indexed with the filename as the media id. Image short-ids and named
files coexist in one folder.
"""

__all__ = (
    "MediaItem",
    "MediaLibrary",
    "mime_for_name",
)

import base64
import dataclasses
import os
import re
import time

# Filename extension <-> mime, for the media types the agent moves around.
# Anything unknown degrades to application/octet-stream (download-only).
_MIME_BY_EXT = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
    "tif": "image/tiff", "tiff": "image/tiff", "exr": "image/x-exr",
    "hdr": "image/vnd.radiance", "svg": "image/svg+xml",
    "stl": "model/stl", "obj": "model/obj", "ply": "model/ply",
    "gltf": "model/gltf+json", "glb": "model/gltf-binary",
    "fbx": "model/fbx", "usd": "model/usd", "usda": "model/usd",
    "usdc": "model/usd", "usdz": "model/vnd.usdz+zip", "abc": "model/abc",
    "blend": "application/x-blender",
    "wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg",
    "flac": "audio/flac", "aif": "audio/aiff", "aiff": "audio/aiff",
    "pdf": "application/pdf",
}
_EXT_BY_MIME = {mime: ext for ext, mime in reversed(list(_MIME_BY_EXT.items()))}

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._ ()+-]+")


def mime_for_name(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _MIME_BY_EXT.get(ext, "application/octet-stream")


def _safe_name(filename: str) -> str:
    base = os.path.basename(filename.replace("\\", "/")).strip()
    base = _SAFE_NAME_RE.sub("_", base).lstrip(".")
    return base or "file"


def _is_short_id(stem: str) -> bool:
    return stem.startswith("i") and stem[1:].isdigit()


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
            "size": os.path.getsize(self.path) if os.path.isfile(self.path) else 0,
        }


class MediaLibrary:
    """
    Disk-backed registry for one session's media: short-id images
    (``i<N>.<ext>``) plus named files (id == filename).
    """

    def __init__(self, directory: str) -> None:
        self._dir = directory
        self._items: dict[str, MediaItem] = {}
        self._counter = 0
        self._load_existing()

    @property
    def directory(self) -> str:
        """
        The on-disk folder — also the session's media-IO jail.
        """
        return self._dir

    def _index_file(self, filename: str) -> MediaItem | None:
        path = os.path.join(self._dir, filename)
        if not os.path.isfile(path):
            return None
        stem, _sep, rest = filename.partition(".")
        if _is_short_id(stem):
            media_id = stem
            self._counter = max(self._counter, int(stem[1:]))
            mime = _MIME_BY_EXT.get(rest.lower(), "image/{:s}".format(rest or "png"))
            label = ""
        else:
            media_id = filename
            mime = mime_for_name(filename)
            label = filename
        item = MediaItem(
            media_id=media_id,
            mime=mime,
            label=label,
            path=path,
            created=os.path.getmtime(path),
        )
        self._items[media_id] = item
        return item

    def _load_existing(self) -> None:
        if not os.path.isdir(self._dir):
            return
        for filename in sorted(os.listdir(self._dir)):
            self._index_file(filename)

    def refresh(self) -> list[str]:
        """
        Pick up files written into the folder by someone else (the
        ``media_io`` tool writes exports from inside Blender). Returns
        the ids of newly indexed items.
        """
        if not os.path.isdir(self._dir):
            return []
        before = set(self._items)
        for filename in sorted(os.listdir(self._dir)):
            stem = filename.partition(".")[0]
            media_id = stem if _is_short_id(stem) else filename
            if media_id not in self._items:
                self._index_file(filename)
        return [media_id for media_id in self._items if media_id not in before]

    def register_base64(self, data_b64: str, mime: str, label: str) -> str:
        """
        Store a base64 payload and return its short id.
        """
        return self.register_bytes(base64.b64decode(data_b64), mime=mime, label=label)

    def register_bytes(self, data: bytes, mime: str, label: str) -> str:
        self._counter += 1
        media_id = "i{:d}".format(self._counter)
        ext = _EXT_BY_MIME.get(mime) or mime.rsplit("/", 1)[-1] or "bin"
        ext = _SAFE_NAME_RE.sub("", ext.split("+")[0]) or "bin"
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

    def register_named_bytes(self, data: bytes, filename: str, mime: str | None = None) -> str:
        """
        Store a user attachment under its own (sanitized,
        collision-suffixed) filename; the filename is the media id.
        """
        name = _safe_name(filename)
        os.makedirs(self._dir, exist_ok=True)
        stem, dot, ext = name.rpartition(".")
        candidate = name
        counter = 2
        while os.path.exists(os.path.join(self._dir, candidate)):
            candidate = ("{:s}-{:d}{:s}{:s}".format(stem, counter, dot, ext)
                         if dot else "{:s}-{:d}".format(name, counter))
            counter += 1
        path = os.path.join(self._dir, candidate)
        with open(path, "wb") as fh:
            fh.write(data)
        self._items[candidate] = MediaItem(
            media_id=candidate,
            mime=mime or mime_for_name(candidate),
            label=filename,
            path=path,
            created=time.time(),
        )
        return candidate

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
