"""Claude CLI client for PR reviews."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from src.config import Config


class ClaudeClient:
    """Client for interacting with Claude via CLI."""

    def __init__(self, config: Config, project_root: Path) -> None:
        """Initialize the Claude client.

        Args:
            config: Application configuration
            project_root: Root path of the Unity project to analyze
        """
        self.config = config
        self.project_root = project_root

    def _build_command(
        self,
        system_prompt: str,
        debug: bool = False,
        json_schema: str | None = None,
        enable_tools: bool | str = False,
        model: str | None = None,
    ) -> list[str]:
        """Build the claude CLI command.

        Args:
            system_prompt: System prompt for the session
            debug: Whether to enable debug output
            json_schema: Optional JSON schema for structured output
            enable_tools: Tool mode - False (no tools), "read_only" (Read only), True (all tools)
            model: Model to use (defaults to config.claude.model)

        Returns:
            Command list for subprocess (user message will be passed via stdin)
        """
        cmd = [
            "claude",
            "-p",  # Print mode (non-interactive)
            "--output-format", "json",
            "--model", model or self.config.claude.model,
            "--system-prompt", system_prompt,
        ]

        if enable_tools == "read_only":
            # Enable only Read tool for Phase 1 (analysis only)
            cmd.extend(["--tools", "Read"])
            cmd.extend(["--permission-mode", "bypassPermissions"])
        elif enable_tools:
            # Enable built-in tools for file editing, compilation, and git operations
            cmd.extend(["--tools", "Read,Edit,Bash"])
            cmd.extend(["--permission-mode", "bypassPermissions"])

        if json_schema:
            cmd.extend(["--json-schema", json_schema])

        if debug:
            cmd.extend(["--debug"])

        return cmd

    # JSON Schema for Phase 1: Review analysis only (no fix application)
    FINDINGS_SCHEMA = json.dumps({
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_file": {
                            "type": "string",
                            "description": "問題が発見されたファイルパス"
                        },
                        "source_line": {
                            "type": "integer",
                            "description": "問題が発見された行番号"
                        },
                        "source_line_end": {
                            "type": "integer",
                            "description": "問題箇所の終了行番号（オプション）"
                        },
                        "title": {
                            "type": "string",
                            "description": "問題の簡潔なタイトル（日本語）"
                        },
                        "description": {
                            "type": "string",
                            "description": "問題の説明（日本語、1-2文）"
                        },
                        "scenario": {
                            "type": "string",
                            "description": "問題が発生する具体的なシナリオ（ステップバイステップ、コード例付き）"
                        },
                        "fix_plan": {
                            "type": "string",
                            "description": "修正計画（どのように修正するかの説明）"
                        },
                        "fix_summary": {
                            "type": "string",
                            "description": "修正方法の簡潔な要約（1-2文、PRコメント表示用）"
                        }
                    },
                    "required": ["source_file", "source_line", "title", "description", "scenario", "fix_plan", "fix_summary"]
                }
            }
        },
        "required": ["findings"]
    })

    # JSON Schema for Phase 3: Fix application result (commit_hash is required)
    FIX_RESULT_SCHEMA = json.dumps({
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "修正を適用したファイルパス"
            },
            "line": {
                "type": "integer",
                "description": "修正を適用した行番号"
            },
            "line_end": {
                "type": "integer",
                "description": "修正範囲の終了行番号"
            },
            "commit_hash": {
                "type": "string",
                "description": "git rev-parse HEADで取得した40文字のコミットハッシュ"
            }
        },
        "required": ["file", "line", "commit_hash"]
    })

    def run_review(
        self,
        system_prompt: str,
        user_message: str,
        on_output: Callable[[str], None] | None = None,
        debug: bool = False,
        enable_tools: bool | str = False,
        env_vars: dict[str, str] | None = None,
        json_schema: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Run a review using Claude CLI.

        Args:
            system_prompt: System prompt for the reviewer
            user_message: User message with review instructions
            on_output: Callback for streaming output
            debug: Whether to enable debug output
            enable_tools: Tool mode - False (no tools), "read_only" (Read only), True (all tools)
            env_vars: Additional environment variables to pass to Claude
            json_schema: Custom JSON schema (defaults based on enable_tools)
            model: Model to use (defaults to config.claude.model)

        Returns:
            Result dictionary with response and parsed findings
        """
        import os

        # Use FIX_RESULT_SCHEMA for Phase 3 (full tools), FINDINGS_SCHEMA for Phase 1
        if json_schema is None:
            json_schema = self.FIX_RESULT_SCHEMA if enable_tools is True else self.FINDINGS_SCHEMA

        cmd = self._build_command(
            system_prompt=system_prompt,
            debug=debug,
            json_schema=json_schema,
            enable_tools=enable_tools,
            model=model,
        )

        # Prepare environment with additional variables
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        try:
            # Run claude CLI with user message via stdin
            # Longer timeout when tools are enabled (file edits, compilation, commits take time)
            timeout = 600 if enable_tools else 300  # 10 min with tools, 5 min without
            result = subprocess.run(
                cmd,
                input=user_message,
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                timeout=timeout,
                env=env,
            )

            if result.returncode != 0:
                return {
                    "status": "error",
                    "error": result.stderr or "Unknown error",
                    "findings": [],
                }

            # Parse JSON output
            try:
                response = json.loads(result.stdout)
            except json.JSONDecodeError:
                # If not valid JSON, treat as plain text
                response = {"result": result.stdout}

            # Extract findings from response
            findings = self._extract_findings(response)

            # Get the text response
            text_response = self._extract_text_response(response)

            # Extract cost information
            cost_usd = response.get("total_cost_usd", 0.0)

            if on_output:
                on_output(text_response)

            return {
                "status": "completed",
                "response": response,
                "text": text_response,
                "findings": findings,
                "cost_usd": cost_usd,
                "stderr": result.stderr if result.stderr else None,
            }

        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "error": "Review timed out after 5 minutes",
                "findings": [],
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "findings": [],
            }

    def _extract_findings(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract findings from Claude's response.

        Args:
            response: Parsed JSON response from Claude CLI

        Returns:
            List of finding dictionaries
        """
        # Check structured_output first (from --json-schema)
        structured_output = response.get("structured_output")
        if structured_output and isinstance(structured_output, dict):
            # Phase 1: findings array
            if "findings" in structured_output:
                return structured_output["findings"]
            # Phase 3: Single fix result with commit_hash
            if "commit_hash" in structured_output:
                return [structured_output]

        findings = []

        # Look for result field
        result = response.get("result", "")

        # If result is a string, try to parse it as JSON first
        if isinstance(result, str):
            try:
                parsed_result = json.loads(result)
                if isinstance(parsed_result, dict):
                    if "findings" in parsed_result:
                        return parsed_result["findings"]
                    # Phase 3: Single fix result
                    if "commit_hash" in parsed_result:
                        return [parsed_result]
            except json.JSONDecodeError:
                pass
            # Fall back to text parsing
            findings.extend(self._parse_findings_from_text(result))
        elif isinstance(result, dict):
            if "findings" in result:
                return result["findings"]
            # Phase 3: Single fix result
            if "commit_hash" in result:
                return [result]

        return findings

    def _extract_text_response(self, response: dict[str, Any]) -> str:
        """Extract text response from Claude's output.

        Args:
            response: Parsed JSON response

        Returns:
            Text content
        """
        if "result" in response:
            return str(response["result"])
        return json.dumps(response, ensure_ascii=False, indent=2)

    def _parse_findings_from_text(self, text: str) -> list[dict[str, Any]]:
        """Parse findings from text response.

        Looks for structured finding markers in the text.

        Args:
            text: Text response from Claude

        Returns:
            List of parsed findings
        """
        findings = []
        import re

        # Find all ```json blocks - handle nested code blocks in content
        # Strategy: find ```json, then find matching ``` by counting braces
        json_block_starts = [m.end() for m in re.finditer(r'```json\s*', text)]

        for start_pos in json_block_starts:
            # Find the JSON object start
            if start_pos >= len(text) or text[start_pos] != '{':
                continue

            # Track brace depth to find the matching closing brace
            depth = 0
            end_pos = start_pos
            in_string = False
            escape_next = False

            for i in range(start_pos, len(text)):
                char = text[i]

                if escape_next:
                    escape_next = False
                    continue

                if char == '\\':
                    escape_next = True
                    continue

                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue

                if not in_string:
                    if char == '{':
                        depth += 1
                    elif char == '}':
                        depth -= 1
                        if depth == 0:
                            end_pos = i + 1
                            break

            if depth == 0 and end_pos > start_pos:
                json_str = text[start_pos:end_pos]
                try:
                    data = json.loads(json_str)
                    if "number" in data or "finding" in data or "title" in data:
                        findings.append(data)
                except json.JSONDecodeError:
                    continue

        # Also look for structured finding format in plain text
        # Format: [FINDING] number=N file=path line=N title="..." description="..."
        finding_pattern = r'\[FINDING\]\s+number=(\d+)\s+file=([^\s]+)\s+line=(\d+)\s+title="([^"]+)"\s+description="([^"]+)"'
        plain_matches = re.findall(finding_pattern, text)

        for match in plain_matches:
            findings.append({
                "number": int(match[0]),
                "file": match[1],
                "line": int(match[2]),
                "title": match[3],
                "description": match[4],
            })

        return findings

    def create_single_message(
        self,
        system_prompt: str,
        user_message: str,
    ) -> str:
        """Create a single message without tool use.

        Args:
            system_prompt: System prompt
            user_message: User message

        Returns:
            Claude's text response
        """
        cmd = [
            "claude",
            "-p",
            "--output-format", "text",
            "--model", self.config.claude.model,
            "--system-prompt", system_prompt,
        ]

        try:
            result = subprocess.run(
                cmd,
                input=user_message,
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                timeout=60,
            )

            if result.returncode != 0:
                return f"Error: {result.stderr}"

            return result.stdout.strip()

        except Exception as e:
            return f"Error: {e}"
