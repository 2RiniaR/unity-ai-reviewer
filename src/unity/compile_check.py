"""Unity compile check script for use in reviewer subprocess.

This script can be invoked via:
  python3 -m pr_reviewer.unity.compile_check [--project-path PATH]

It runs Unity compilation and returns exit code 0 on success, 1 on failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.unity.compiler import UnityCompiler


def main() -> int:
    """Run Unity compilation and report result."""
    parser = argparse.ArgumentParser(description="Run Unity compilation check")
    parser.add_argument(
        "--project-path",
        type=str,
        default=".",
        help="Path to Unity project (default: current directory)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force recompile",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )
    args = parser.parse_args()

    project_path = Path(args.project_path).resolve()
    compiler = UnityCompiler(project_path)

    result = compiler.compile(force_recompile=args.force)

    if args.json:
        output = {
            "success": result.success,
            "error_count": result.error_count,
            "warning_count": result.warning_count,
            "errors": [
                {"message": e.message, "file": e.file, "line": e.line}
                for e in result.errors
            ],
            "warnings": [
                {"message": w.message, "file": w.file, "line": w.line}
                for w in result.warnings
            ],
            "execution_time_ms": result.execution_time_ms,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        if result.success:
            print(f"Compilation successful (warnings: {result.warning_count})")
            if result.execution_time_ms:
                print(f"Execution time: {result.execution_time_ms}ms")
        else:
            print(f"Compilation failed with {result.error_count} error(s)")
            for error in result.errors:
                location = f"{error.file}:{error.line}" if error.file else ""
                print(f"  ERROR: {location} {error.message}")

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
