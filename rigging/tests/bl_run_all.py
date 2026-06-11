# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Headless test entrypoint, run inside Blender:

    blender --background --factory-startup --python-exit-code 1 \\
        --python tests/bl_run_all.py -- -v [--tier property|deform|render|all]

Arguments after ``--`` are for this script. Exits nonzero on any failure
(via ``--python-exit-code``).
"""

__all__ = ()

import argparse
import os
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_RIGGING_DIR = os.path.dirname(_TESTS_DIR)

if _RIGGING_DIR not in sys.path:
    sys.path.insert(0, _RIGGING_DIR)

# Deliberate test failures must not pollute the production failure log.
import tempfile
os.environ.setdefault("BLRIG_LOG_DIR", tempfile.mkdtemp(prefix="blrig_test_logs_"))

# Test-module filename prefix per tier. "property" covers perception,
# standard & skill postcondition tests; the heavier tiers are opt-in groups.
_TIER_PATTERNS = {
    "property": ("test_*.py",),
    "deform": ("deform_*.py",),
    "render": ("render_*.py",),
    "all": ("test_*.py", "deform_*.py", "render_*.py"),
}


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--tier", default="all", choices=sorted(_TIER_PATTERNS))
    parser.add_argument("--match", default=None, help="Only run test files matching this glob.")
    args = parser.parse_args(argv)

    patterns = (args.match,) if args.match else _TIER_PATTERNS[args.tier]

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(loader.discover(_TESTS_DIR, pattern=pattern, top_level_dir=_RIGGING_DIR))

    runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1, buffer=False)
    result = runner.run(suite)
    if not result.wasSuccessful():
        # `--python-exit-code 1` turns this into Blender's exit code.
        raise SystemExit(1)


if __name__ == "__main__":
    main()
