#!/usr/bin/env python3
"""
gawk command parser for shfmt-permissions.

Simple wrapper that delegates to awk.py since gawk and awk have compatible syntax.
gawk (GNU awk) is a superset of awk, so the same parsing logic applies.

Input (JSON on stdin):
    {"arguments": ["-v", "x=1", "{ print $1 }", "file.txt"]}

Output (JSON on stdout):
    Same as awk.py output.
"""

import importlib.util
import sys
from pathlib import Path

# Load awk module from same directory
awk_path = Path(__file__).parent / "awk.py"
spec = importlib.util.spec_from_file_location("awk", awk_path)
awk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(awk)


def main():
    """Main entry point - delegates to awk.main()."""
    awk.main()


if __name__ == "__main__":
    main()
