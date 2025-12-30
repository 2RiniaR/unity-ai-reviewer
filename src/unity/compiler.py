"""Unity compiler integration via uLoopMCP."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CompileError:
    """A compile error or warning."""

    message: str
    file: str
    line: int


@dataclass
class CompileResult:
    """Result of Unity compilation."""

    success: bool
    error_count: int
    warning_count: int
    errors: list[CompileError]
    warnings: list[CompileError]
    message: str | None = None
    execution_time_ms: int | None = None


class UnityCompiler:
    """Unity compiler using uLoopMCP.

    Uses Claude CLI to call the uLoopMCP compile tool. The MCP server
    must be running in Unity Editor and configured in the project's
    .mcp.json file.
    """

    def __init__(self, unity_project_path: Path) -> None:
        """Initialize the compiler.

        Args:
            unity_project_path: Path to the Unity project root
        """
        self.unity_project_path = unity_project_path

    def compile(self, force_recompile: bool = False) -> CompileResult:
        """Run Unity compilation via uLoopMCP.

        Args:
            force_recompile: Whether to force a full recompile

        Returns:
            CompileResult with success status and any errors/warnings
        """
        # Build the prompt to call the compile tool
        prompt = f"""uLoopMCPのcompileツールを使用してUnityをコンパイルしてください。

ForceRecompile: {str(force_recompile).lower()}

コンパイル結果をそのまま返してください。"""

        cmd = [
            "claude",
            "-p",
            "--output-format", "json",
            "--model", "haiku",  # Use fast model for simple MCP calls
            "--system-prompt", "あなたはUnityコンパイルを実行するアシスタントです。uLoopMCPのcompileツールを呼び出し、結果を返してください。",
        ]

        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                cwd=str(self.unity_project_path),
                timeout=180,  # 3 minute timeout for compilation
            )

            if result.returncode != 0:
                return CompileResult(
                    success=False,
                    error_count=1,
                    warning_count=0,
                    errors=[CompileError(
                        message=f"Claude CLI error: {result.stderr}",
                        file="",
                        line=0,
                    )],
                    warnings=[],
                    message="Failed to run Claude CLI",
                )

            # Debug: print raw output
            import sys
            if "--debug" in sys.argv:
                print(f"[DEBUG] stdout: {result.stdout[:2000]}")
                if result.stderr:
                    print(f"[DEBUG] stderr: {result.stderr[:500]}")

            # Parse the response
            return self._parse_compile_result(result.stdout)

        except subprocess.TimeoutExpired:
            return CompileResult(
                success=False,
                error_count=1,
                warning_count=0,
                errors=[CompileError(
                    message="Compilation timed out after 3 minutes",
                    file="",
                    line=0,
                )],
                warnings=[],
                message="Timeout",
            )
        except Exception as e:
            return CompileResult(
                success=False,
                error_count=1,
                warning_count=0,
                errors=[CompileError(
                    message=f"Exception: {e}",
                    file="",
                    line=0,
                )],
                warnings=[],
                message=str(e),
            )

    def _parse_compile_result(self, output: str) -> CompileResult:
        """Parse the compile result from Claude CLI output.

        Args:
            output: JSON output from Claude CLI

        Returns:
            Parsed CompileResult
        """
        try:
            response = json.loads(output)
        except json.JSONDecodeError:
            return CompileResult(
                success=False,
                error_count=1,
                warning_count=0,
                errors=[CompileError(
                    message=f"Failed to parse response: {output[:500]}",
                    file="",
                    line=0,
                )],
                warnings=[],
                message="Parse error",
            )

        # Extract the result text which should contain MCP tool response
        result_text = response.get("result", "")

        # Try to find the MCP tool response in the result
        # The compile tool returns a structured response
        compile_data = self._extract_compile_data(result_text, response)

        if compile_data is None:
            return CompileResult(
                success=False,
                error_count=1,
                warning_count=0,
                errors=[CompileError(
                    message=f"Could not extract compile result from response",
                    file="",
                    line=0,
                )],
                warnings=[],
                message="Extraction failed",
            )

        # Parse errors
        errors = []
        for err in compile_data.get("Errors", []):
            errors.append(CompileError(
                message=err.get("Message", "Unknown error"),
                file=err.get("File", ""),
                line=err.get("Line", 0),
            ))

        # Parse warnings
        warnings = []
        for warn in compile_data.get("Warnings", []):
            warnings.append(CompileError(
                message=warn.get("Message", "Unknown warning"),
                file=warn.get("File", ""),
                line=warn.get("Line", 0),
            ))

        return CompileResult(
            success=compile_data.get("Success", False),
            error_count=compile_data.get("ErrorCount", len(errors)),
            warning_count=compile_data.get("WarningCount", len(warnings)),
            errors=errors,
            warnings=warnings,
            message=compile_data.get("Message"),
            execution_time_ms=compile_data.get("ExecutionTimeMs"),
        )

    def _extract_compile_data(
        self,
        result_text: str,
        response: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Extract compile data from various response formats.

        Args:
            result_text: The result text from Claude
            response: Full response dict

        Returns:
            Compile data dict or None if not found
        """
        # Check if result_text is JSON
        if isinstance(result_text, str):
            try:
                data = json.loads(result_text)
                if "Success" in data:
                    return data
            except json.JSONDecodeError:
                pass

        # Look for JSON in the text
        import re
        json_match = re.search(r'\{[^{}]*"Success"[^{}]*\}', result_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Check structured_output from --json-schema
        structured = response.get("structured_output")
        if structured and isinstance(structured, dict):
            if "Success" in structured:
                return structured

        # Parse from natural language response (fallback)
        # Look for patterns like "成功", "エラー数: 0", etc.
        if isinstance(result_text, str):
            # Check for connection errors first
            connection_error_indicators = [
                "MCPサーバーが接続されていない",
                "uLoopMCPが正しく設定されていない",
                "接続確認が必要",
                "MCP server is not connected",
            ]
            if any(ind in result_text for ind in connection_error_indicators):
                return {
                    "Success": False,
                    "ErrorCount": 1,
                    "WarningCount": 0,
                    "Errors": [{
                        "Message": "uLoopMCP server is not connected. Please start Unity and the uLoopMCP server.",
                        "File": "",
                        "Line": 0,
                    }],
                    "Warnings": [],
                    "Message": "MCP connection error",
                }

            # Check for success indicators
            success_indicators = ["成功", "正常に完了", "Success: はい", "成功**: はい"]
            failure_indicators = ["失敗", "エラーが発生", "Success: いいえ"]

            is_success = any(ind in result_text for ind in success_indicators)
            is_failure = any(ind in result_text for ind in failure_indicators)

            if is_success or is_failure:
                # Extract error/warning counts
                error_match = re.search(r'エラー[数]?[：:\s]*(\d+)', result_text)
                warning_match = re.search(r'警告[数]?[：:\s]*(\d+)', result_text)

                error_count = int(error_match.group(1)) if error_match else 0
                warning_count = int(warning_match.group(1)) if warning_match else 0

                # Extract execution time
                time_match = re.search(r'実行時間[：:\s]*([\d,]+)\s*ms', result_text)
                execution_time = int(time_match.group(1).replace(",", "")) if time_match else None

                return {
                    "Success": is_success and not is_failure and error_count == 0,
                    "ErrorCount": error_count,
                    "WarningCount": warning_count,
                    "Errors": [],
                    "Warnings": [],
                    "ExecutionTimeMs": execution_time,
                    "Message": "Parsed from natural language response",
                }

        return None
