# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Regression test for the truncated-large-response bug: ``sendall`` on a
NON-blocking socket raises ``BlockingIOError`` after a partial write once
the payload exceeds the kernel send buffer, which the interactive bridge
used to swallow — truncating screenshots/renders into
"Invalid response ... Unterminated string" client errors.

Tests the addon's ``send_response`` directly over a socketpair with tiny
buffers; no Blender required (the server module has no top-level bpy
import).
"""

__all__ = ()

import importlib.util
import json
import os
import socket
import sys
import threading
import unittest

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SERVER_PATH = os.path.join(
    _REPO_DIR, "addon", "blender_mcp_addon", "mcp_to_blender_server.py")


def _load_server_module():
    spec = importlib.util.spec_from_file_location("_bridge_server_under_test", _SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tiny_buffer_pair() -> tuple[socket.socket, socket.socket]:
    sender, receiver = socket.socketpair()
    # Force partial writes: payload >> kernel buffers.
    sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8192)
    receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192)
    return sender, receiver


def _drain(receiver: socket.socket, out: bytearray) -> None:
    while True:
        chunk = receiver.recv(65536)
        if not chunk:
            break
        out.extend(chunk)
        if b"\0" in out:
            break


class TestSendResponse(unittest.TestCase):

    def test_large_response_flushes_completely(self) -> None:
        server = _load_server_module()
        # A response well past any kernel send buffer (≈5 MB).
        response = {"status": "ok", "result": {"image_b64": "x" * 5_000_000}}

        sender, receiver = _tiny_buffer_pair()
        sender.setblocking(False)  # the interactive server's client state
        received = bytearray()
        drainer = threading.Thread(target=_drain, args=(receiver, received))
        drainer.start()
        try:
            server.send_response(sender, response)
        finally:
            sender.close()
            drainer.join(timeout=30)
            receiver.close()

        payload, sep, _rest = bytes(received).partition(b"\0")
        self.assertEqual(sep, b"\0", "response was not fully delimited")
        decoded = json.loads(payload.decode("utf-8"))
        self.assertEqual(len(decoded["result"]["image_b64"]), 5_000_000)

    def test_nonblocking_sendall_truncates_demo(self) -> None:
        """
        Documents the failure mode the fix removes: non-blocking sendall
        partial-writes then raises; a client reading afterwards sees a
        truncated (unparseable) response.
        """
        sender, receiver = _tiny_buffer_pair()
        sender.setblocking(False)
        payload = (json.dumps({"big": "x" * 5_000_000}) + "\0").encode("utf-8")
        with self.assertRaises(BlockingIOError):
            sender.sendall(payload)
        sender.close()
        received = bytearray()
        _drain(receiver, received)
        receiver.close()
        self.assertNotIn(b"\0", received)  # truncated: no delimiter arrived
        self.assertLess(len(received), len(payload))


if __name__ == "__main__":
    unittest.main()
