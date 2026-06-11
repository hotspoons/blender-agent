# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tool-code for reading an image file back through the bridge, downscaled
to fit the MCP message size limit.

Shared by the ``render_*_to_path`` tools so the rendered image can be
attached to the tool result (vision-capable agents see what they made
instead of only a file path). The file is read on the Blender side -
the MCP server may not share a filesystem with Blender.
"""

__all__ = (
    "Params",
    "Result",
    "main",
)

from typing import NamedTuple

# Keep base64 comfortably under the typical 1 MiB MCP message limit.
_IMAGE_SIZE_LIMIT_IN_BYTES = (1_048_576 * 3) // 4


class Params(NamedTuple):
    filepath: str
    size_limit_in_bytes: int = 0


class Result(NamedTuple):
    status: str
    image_base64: str | None = None
    message: str | None = None


# NOTE: this stub is never executed. `toolcode_load_from_filepath`
# replaces the block below at load time with the real implementation
# from the referenced template, which downscales via Blender's bundled
# `imbuf` module (Blender ships no PIL; imbuf is its native image API).
# The stub only keeps this file valid Python for editors and linters.
# @include_begin: _template_image_downscale_to_size_limit.py
def _image_downscale_to_size_limit(
        tmpdir: str, filepath: str,
        size_limit_in_bytes: int,
        size_tolerance_in_bytes: int = 0,
) -> bytes:
    raise NotImplementedError
# @include_end


def main(params: Params) -> Result:
    import base64
    import os
    import tempfile

    if not os.path.isfile(params.filepath):
        return Result(status="error", message="file not found: {:s}".format(params.filepath))

    size_limit = params.size_limit_in_bytes if params.size_limit_in_bytes > 0 else _IMAGE_SIZE_LIMIT_IN_BYTES
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            data = _image_downscale_to_size_limit(tmpdir, params.filepath, size_limit)
    except Exception as ex:  # pylint: disable=broad-exception-caught
        return Result(status="error", message=str(ex))
    return Result(status="ok", image_base64=base64.b64encode(data).decode("ascii"))
