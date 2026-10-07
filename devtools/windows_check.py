"""Run the test suite the way Windows would, on a machine that is not Windows.

Three bugs so far passed every test on Linux and failed on the user's Windows
machine:

  * SO_REUSEADDR means the opposite thing on Windows, so a port probe reported
    busy ports as free (2.3.1).
  * open() without an encoding inherits cp1252 instead of UTF-8, and the static
    assets contain bytes cp1252 cannot decode (2.7.1).
  * the console code page cannot represent an em dash, so analyze.py and
    run.py --help crashed when redirected (2.7.1).

Each one was found by the user, on their machine, after a release. This script
exists so that stops happening: it re-runs the suite with any open() that does
not name an encoding forced to behave as Windows would.

    python devtools/windows_check.py            # simulate the cp1252 default
    python devtools/windows_check.py --cp850    # simulate a French console

It cannot catch everything - it does not know about sockets or the filesystem -
but it catches the whole encoding class, and that class has bitten three times.
"""
from __future__ import annotations

import builtins
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main() -> int:
    cp850 = "--cp850" in sys.argv
    real_open = builtins.open

    def win_open(file, mode="r", *args, **kwargs):
        if isinstance(mode, str):
            if "b" in mode:
                kwargs.pop("encoding", None)
            elif "encoding" not in kwargs:
                # what Windows does when you do not say otherwise
                kwargs["encoding"] = "cp1252"
        return real_open(file, mode, *args, **kwargs)

    builtins.open = win_open
    if cp850:
        os.environ["PYTHONIOENCODING"] = "cp850"
    else:
        os.environ.pop("PYTHONIOENCODING", None)

    print("running the suite as Windows would"
          + (" (cp850 console)" if cp850 else " (cp1252 file encoding)"))
    try:
        runpy.run_path(os.path.join(ROOT, "tests.py"), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
