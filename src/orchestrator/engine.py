"""Main orchestrator engine for iterative PR review."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.claude import ClaudeClient
from src.claude.base_prompt import get_exploration_prompt, get_reviewer_prompt
from src.config import Config
from src.models import (
    ExplorationItem,
    Finding,
    Metadata,
    Phase,
    PRInfo,
    ReviewerType,
    Status,
)
from src.orchestrator.metadata import MetadataHandler

console = Console()


class ReviewOrchestrator:
    """Orchestrates the iterative PR review process."""

    def __init__(
        self,
        config: Config,
        reviews_dir: Path,
        debug: bool = False,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            config: Application configuration
            reviews_dir: Directory for storing review data
            debug: Whether to enable debug output
        """
        self.config = config
        self.debug = debug
        self.metadata_handler = MetadataHandler(reviews_dir)
        self.claude_client = ClaudeClient(config, config.project.unity_project_path)
        self.review_path: Path | None = None
        self.metadata: Metadata | None = None
        self.pr_diff: str | None = None
        self._lock = threading.Lock()  # For thread-safe metadata access
        self._env_vars: dict[str, str] = {}  # Environment variables for Claude

    def set_env_vars(
        self,
        fix_branch: str,
        target_branch: str,
        repo_owner: str,
        repo_name: str,
        original_pr_number: int,
        fix_pr_number: int | None = None,
    ) -> None:
        """Set environment variables for Claude's Bash commands.

        Args:
            fix_branch: Branch name for fixes
            target_branch: Target branch for merge
            repo_owner: Repository owner
            repo_name: Repository name
            original_pr_number: Original PR number being reviewed
            fix_pr_number: Fix PR number if already created
        """
        self._env_vars = {
            "FIX_BRANCH": fix_branch,
            "TARGET_BRANCH": target_branch,
            "REPO_OWNER": repo_owner,
            "REPO_NAME": repo_name,
            "ORIGINAL_PR_NUMBER": str(original_pr_number),
            "FIX_PR_NUMBER": str(fix_pr_number) if fix_pr_number else "",
        }

    def start_review(
        self,
        pr_info: PRInfo,
        changed_files: list[dict[str, Any]],
        pr_diff: str | None = None,
    ) -> Metadata:
        """Start a new PR review.

        Args:
            pr_info: Pull request information
            changed_files: List of changed files from GitHub API
            pr_diff: Optional diff content for change-focused review

        Returns:
            Metadata object for the review
        """
        console.print(Panel(f"PR #{pr_info.number} のレビューを開始", title="PR Review"))
        self.pr_diff = pr_diff

        # Create review folder and metadata
        self.review_path, self.metadata = self.metadata_handler.create_review(pr_info)

        # Initialize changed files
        from src.models.metadata import ChangedFile

        self.metadata.changed_files = [
            ChangedFile(
                path=f["filename"],
                status=f["status"],
                additions=f.get("additions", 0),
                deletions=f.get("deletions", 0),
            )
            for f in changed_files
        ]

        # Write context files for efficient Claude CLI processing
        context_dir = self.review_path / "context"
        context_dir.mkdir(exist_ok=True)

        # Write changed files list
        changed_files_content = "\n".join(
            f"- {f['filename']} ({f['status']}, +{f.get('additions', 0)}/-{f.get('deletions', 0)})"
            for f in changed_files
        )
        (context_dir / "changed_files.txt").write_text(changed_files_content)

        # Write diff
        if pr_diff:
            (context_dir / "diff.patch").write_text(pr_diff)

        # Initialize exploration queue with changed files
        for f in self.metadata.changed_files:
            if f.status != "deleted":  # Don't explore deleted files
                self.metadata.add_exploration_item(
                    file=f.path,
                    reason="directly_changed",
                    priority=1,
                    depth=0,
                )

        # Update phase
        self.metadata.review_state.phases.initialization = Status.COMPLETED
        self.metadata.review_state.current_phase = Phase.EXPLORATION
        self.metadata_handler.save_metadata(self.review_path, self.metadata)

        console.print(f"[green]{len(self.metadata.changed_files)} 個のファイルでレビューを初期化しました[/green]")
        return self.metadata

    def run_review_phase(self, focus_on_changes: bool = True) -> None:
        """Run the deep analysis phase with all reviewers in parallel.

        Phase 1: Analysis only - no file edits or commits.
        Findings are stored with fix_plan for later application in Phase 3.

        Args:
            focus_on_changes: If True, focus on changes only. If False, review entire files.
        """
        if self.metadata is None or self.review_path is None:
            raise RuntimeError("Review not initialized")

        self._focus_on_changes = focus_on_changes

        console.print(Panel("深層分析フェーズを開始（並列実行）", title="Phase: Deep Analysis"))
        self.metadata.review_state.phases.deep_analysis = Status.IN_PROGRESS
        self.metadata_handler.save_metadata(self.review_path, self.metadata)

        enabled_reviewers = [
            ReviewerType(r) for r in self.config.review.enabled_reviewers
        ]

        console.print(f"[cyan]{len(enabled_reviewers)} 個のレビュワーを並列実行中...[/cyan]")

        # Run all reviewers in parallel for Phase 1 (analysis only)
        with ThreadPoolExecutor(max_workers=len(enabled_reviewers)) as executor:
            futures = {
                executor.submit(self._run_reviewer_analysis, rt): rt
                for rt in enabled_reviewers
            }

            for future in as_completed(futures):
                reviewer_type = futures[future]
                try:
                    findings = future.result()

                    # Process findings from this reviewer
                    with self._lock:
                        for finding_data in findings:
                            # Extract scenario
                            scenario = finding_data.get("scenario") or finding_data.get("reason", "")
                            if scenario:
                                scenario = scenario.replace("\\`\\`\\`", "```")

                            finding = Finding(
                                id=self.metadata.get_next_finding_id(),
                                reviewer=reviewer_type,
                                # Phase 1: No number yet (assigned in Phase 2)
                                number=None,
                                # Phase 1: source location from analysis
                                source_file=finding_data.get("source_file", ""),
                                source_line=finding_data.get("source_line", 0),
                                source_line_end=finding_data.get("source_line_end"),
                                # Phase 1: description
                                title=finding_data.get("title", ""),
                                description=finding_data.get("description", ""),
                                scenario=scenario if scenario else None,
                                fix_plan=finding_data.get("fix_plan"),
                                # Phase 3: Not yet applied
                                file=None,
                                line=None,
                                line_end=None,
                                commit_hash=None,
                            )
                            self.metadata.add_finding(finding)

                            console.print(
                                f"  [yellow]発見[/yellow]: {finding.title} - {reviewer_type.value}"
                            )

                        self.metadata.reviewers[reviewer_type].status = Status.COMPLETED
                        self.metadata_handler.save_metadata(self.review_path, self.metadata)

                    console.print(f"  [green]✓[/green] {reviewer_type.value} 完了 ({len(findings)} 件)")

                except Exception as e:
                    console.print(f"  [red]✗[/red] {reviewer_type.value} エラー: {e}")

        self.metadata.review_state.phases.deep_analysis = Status.COMPLETED
        self.metadata.review_state.current_phase = Phase.FIX_PR_CREATION
        self.metadata_handler.save_metadata(self.review_path, self.metadata)

        console.print(
            f"[green]分析完了。{len(self.metadata.findings)} 件の問題を検出しました。[/green]"
        )

    def _run_reviewer_analysis(
        self, reviewer_type: ReviewerType
    ) -> list[dict[str, Any]]:
        """Run a single reviewer for Phase 1: analysis only (no file edits).

        Args:
            reviewer_type: Type of reviewer to run

        Returns:
            List of finding dictionaries with source_file, source_line, title, description, scenario, fix_plan
        """
        if self.metadata is None or self.review_path is None:
            return []

        console.print(f"  [cyan]開始[/cyan]: {reviewer_type.value}")

        with self._lock:
            self.metadata.reviewers[reviewer_type].status = Status.IN_PROGRESS
            self.metadata_handler.save_metadata(self.review_path, self.metadata)

        system_prompt = get_reviewer_prompt(reviewer_type)

        # Get context file paths
        context_dir = self.review_path / "context"
        changed_files_path = context_dir / "changed_files.txt"
        diff_path = context_dir / "diff.patch"

        # Build user message for Phase 1 (analysis only)
        if getattr(self, '_focus_on_changes', True) and self.pr_diff:
            user_message = self._build_phase1_change_focused_message(
                reviewer_type, changed_files_path, diff_path
            )
        else:
            user_message = self._build_phase1_full_review_message(
                reviewer_type, changed_files_path
            )

        # Save debug input (prompts)
        if self.debug and self.review_path:
            debug_dir = self.review_path / "debug"
            debug_dir.mkdir(exist_ok=True)
            # Save system prompt
            (debug_dir / f"{reviewer_type.value}_system_prompt.txt").write_text(system_prompt)
            # Save user message
            (debug_dir / f"{reviewer_type.value}_user_message.txt").write_text(user_message)

        # Run review using Claude CLI - Read only for Phase 1 (analysis only)
        result = self.claude_client.run_review(
            system_prompt=system_prompt,
            user_message=user_message,
            debug=self.debug,
            enable_tools="read_only",  # Phase 1: Read only, no edits
            env_vars=self._env_vars if self._env_vars else None,
        )

        if self.debug:
            console.print(f"[dim]Debug - {reviewer_type.value}: Status={result.get('status')}, Findings={len(result.get('findings', []))}[/dim]")

        # Save debug response (full JSON response)
        if self.debug and self.review_path:
            debug_dir = self.review_path / "debug"
            debug_dir.mkdir(exist_ok=True)
            # Save raw response JSON
            import json as _json
            response_data = result.get("response", {})
            (debug_dir / f"{reviewer_type.value}_response.json").write_text(
                _json.dumps(response_data, ensure_ascii=False, indent=2)
            )
            # Save stderr if any
            if result.get("stderr"):
                (debug_dir / f"{reviewer_type.value}_stderr.txt").write_text(result.get("stderr", ""))

        return result.get("findings", [])


    def _read_file_lines(
        self,
        file_path: str,
        line_number: int,
        context_lines: int = 0,
    ) -> str | None:
        """Read specific lines from a file.

        Args:
            file_path: Path to the file
            line_number: Target line number (1-based)
            context_lines: Number of lines before/after to include

        Returns:
            The line(s) content, or None if file not found
        """
        # Try to find the file in common locations
        possible_paths = [
            Path(file_path),
            self.config.project.unity_project_path / file_path,
        ]

        for path in possible_paths:
            if path and path.exists():
                try:
                    with open(path, encoding="utf-8") as f:
                        lines = f.readlines()

                    # Adjust for 0-based indexing
                    start = max(0, line_number - 1 - context_lines)
                    end = min(len(lines), line_number + context_lines)

                    return "".join(lines[start:end]).rstrip("\n")
                except Exception:
                    continue

        return None

    def _build_phase1_change_focused_message(
        self,
        reviewer_type: ReviewerType,
        changed_files_path: Path,
        diff_path: Path,
    ) -> str:
        """Build user message for Phase 1 change-focused review (analysis only).

        Args:
            reviewer_type: Type of reviewer
            changed_files_path: Path to the changed files list
            diff_path: Path to the diff file

        Returns:
            User message for the reviewer
        """
        return f"""
以下のPR変更を {reviewer_type.value} の観点でレビューしてください。

## 重要: このフェーズの役割

**分析と修正計画の報告のみを行ってください。**
- ファイルの編集は行わないでください
- コミットは行わないでください
- 修正計画（fix_plan）を詳細に記述してください

## レビュー範囲

**この変更によって発生しうる問題のみを報告してください。**
- 変更されたコードに直接関連する問題
- この変更が原因で既存コードに影響を与える問題
- この変更によって新たに発生する可能性のあるバグ

**以下は報告しないでください:**
- 変更に関係のない既存コードの問題
- 今回の変更とは無関係な改善提案
- 変更前から存在していた問題

## コンテキストファイル

以下のファイルをReadツールで読み込んでレビューを行ってください:

1. 変更ファイル一覧: {changed_files_path}
2. 差分（diff）: {diff_path}

## 手順

1. 上記のファイルをReadツールで読み込む
2. 差分を分析して変更内容を理解する
3. 必要に応じてソースファイル全体を読み込む
4. この変更によって発生しうる問題を特定
5. 問題を発見したら、findingsとして報告（修正計画を含む）

## 出力形式

### 必須フィールド
- source_file: 問題が発見されたファイルパス
- source_line: 問題が発見された行番号
- title: 問題の簡潔なタイトル（日本語）
- description: 問題の説明（日本語、1-2文）
- scenario: 問題が発生する具体的なシナリオ
- fix_plan: 修正計画（どのように修正するかの詳細な説明）

### fix_planの書き方

修正内容を具体的に記述してください:
- 対象ファイルとおおよその行番号
- 変更前のコード（該当部分）
- 変更後のコード（修正案）
- 修正理由

### scenarioテンプレート

1. [トリガーとなる操作]
   ```csharp
   // 該当コード（3-5行程度）
   ```
   → [状態変化の説明]

2. [次の操作]
   ```csharp
   // 該当コード
   ```
   → [状態変化の説明]

3. [問題が発生]
   ```csharp
   // 問題が発生するコード
   ```
   → [例外/不具合の説明]

---

変更に起因する問題が見つからない場合は、findings配列を空にしてください。
回答は日本語でお願いします。
"""

    def _build_phase1_full_review_message(
        self,
        reviewer_type: ReviewerType,
        changed_files_path: Path,
    ) -> str:
        """Build user message for Phase 1 full file review (analysis only).

        Args:
            reviewer_type: Type of reviewer
            changed_files_path: Path to the changed files list

        Returns:
            User message for the reviewer
        """
        return f"""
以下の変更ファイルを {reviewer_type.value} の観点でレビューしてください。

## 重要: このフェーズの役割

**分析と修正計画の報告のみを行ってください。**
- ファイルの編集は行わないでください
- コミットは行わないでください
- 修正計画（fix_plan）を詳細に記述してください

## コンテキストファイル

変更ファイル一覧: {changed_files_path}

## 手順

1. 上記のファイルをReadツールで読み込む
2. 各ソースファイルをReadツールで読み込む
3. レビュー観点に関連する問題を分析
4. 問題を発見したら、findingsとして報告（修正計画を含む）

## 出力形式

### 必須フィールド
- source_file: 問題が発見されたファイルパス
- source_line: 問題が発見された行番号
- title: 問題の簡潔なタイトル（日本語）
- description: 問題の説明（日本語、1-2文）
- scenario: 問題が発生する具体的なシナリオ
- fix_plan: 修正計画（どのように修正するかの詳細な説明）

### fix_planの書き方

修正内容を具体的に記述してください:
- 対象ファイルとおおよその行番号
- 変更前のコード（該当部分）
- 変更後のコード（修正案）
- 修正理由

### scenarioテンプレート

1. [トリガーとなる操作]
   ```csharp
   // 該当コード（3-5行程度）
   ```
   → [状態変化の説明]

2. [次の操作]
   ```csharp
   // 該当コード
   ```
   → [状態変化の説明]

3. [問題が発生]
   ```csharp
   // 問題が発生するコード
   ```
   → [例外/不具合の説明]

---

問題が見つからない場合は、findings配列を空にしてください。
回答は日本語でお願いします。
"""

    def assign_finding_numbers(self) -> None:
        """Assign sequential numbers to findings (Phase 2 preparation).

        This method assigns (1), (2), (3)... numbers to all findings
        in preparation for PR creation and fix application.
        """
        if self.metadata is None or self.review_path is None:
            raise RuntimeError("Review not initialized")

        for i, finding in enumerate(self.metadata.findings, start=1):
            finding.number = i

        self.metadata_handler.save_metadata(self.review_path, self.metadata)
        console.print(f"[cyan]{len(self.metadata.findings)} 件のfindingに番号を割り当てました[/cyan]")

    def run_fix_application_phase(
        self,
        on_finding_fixed: callable | None = None,
    ) -> dict[str, Any]:
        """Run Phase 3: Apply fixes sequentially for each finding.

        For each finding:
        1. Apply the fix using Claude with tools enabled (based on fix_plan)
        2. Run compile check
        3. Commit and push
        4. Update finding with commit_hash and fix location

        Args:
            on_finding_fixed: Optional callback called after each finding is fixed
                             with signature (finding: Finding, success: bool) -> None

        Returns:
            Dict with results: applied_count, failed_count, skipped_count
        """
        if self.metadata is None or self.review_path is None:
            raise RuntimeError("Review not initialized")

        console.print(Panel("修正適用フェーズを開始（直列実行）", title="Phase: Fix Application"))
        self.metadata.review_state.phases.fix_application = Status.IN_PROGRESS
        self.metadata.review_state.current_phase = Phase.FIX_APPLICATION
        self.metadata_handler.save_metadata(self.review_path, self.metadata)

        results = {
            "applied": [],
            "failed": [],
            "skipped": [],
        }

        # Get report-only reviewers from config
        report_only_reviewers = self.config.review.report_only_reviewers

        # Process each finding sequentially
        for finding in self.metadata.findings:
            # Skip findings from report-only reviewers
            if finding.reviewer.value in report_only_reviewers:
                console.print(f"  [dim]スキップ[/dim]: ({finding.number}) {finding.title} - 報告のみ")
                results["skipped"].append(finding.id)
                continue

            if not finding.fix_plan:
                console.print(f"  [dim]スキップ[/dim]: ({finding.number}) {finding.title} - fix_planなし")
                results["skipped"].append(finding.id)
                continue

            console.print(f"  [cyan]修正中[/cyan]: ({finding.number}) {finding.title}")

            try:
                # Apply fix using Claude with tools
                fix_result = self._apply_single_fix(finding)

                if fix_result.get("success"):
                    finding.commit_hash = fix_result.get("commit_hash")
                    finding.file = fix_result.get("file", finding.source_file)
                    finding.line = fix_result.get("line", finding.source_line)
                    finding.line_end = fix_result.get("line_end", finding.source_line_end)

                    results["applied"].append(finding.id)
                    console.print(f"    [green]✓[/green] コミット: {finding.commit_hash[:7] if finding.commit_hash else 'N/A'}")

                    if on_finding_fixed:
                        on_finding_fixed(finding, True)
                else:
                    results["failed"].append(finding.id)
                    error = fix_result.get("error", "Unknown error")
                    console.print(f"    [red]✗[/red] 失敗: {error}")

                    if on_finding_fixed:
                        on_finding_fixed(finding, False)

            except Exception as e:
                results["failed"].append(finding.id)
                console.print(f"    [red]✗[/red] エラー: {e}")

                if on_finding_fixed:
                    on_finding_fixed(finding, False)

            # Save progress after each finding
            self.metadata_handler.save_metadata(self.review_path, self.metadata)

        self.metadata.review_state.phases.fix_application = Status.COMPLETED
        self.metadata_handler.save_metadata(self.review_path, self.metadata)

        console.print(f"\n[green]修正適用完了[/green]")
        console.print(f"  成功: {len(results['applied'])} 件")
        if results["failed"]:
            console.print(f"  [red]失敗: {len(results['failed'])} 件[/red]")
        if results["skipped"]:
            console.print(f"  [dim]スキップ: {len(results['skipped'])} 件[/dim]")

        return results

    def _apply_single_fix(self, finding: Finding) -> dict[str, Any]:
        """Apply a single fix using Claude with tools.

        Args:
            finding: The finding to fix

        Returns:
            Dict with success, commit_hash, file, line, line_end, error
        """
        import re
        import subprocess

        # Record commit count before to detect if a new commit was made
        before_commit = self._get_latest_commit_for_finding(finding.number)

        system_prompt = f"""あなたはUnity C#プロジェクトのコード修正アシスタントです。

## 役割

提供された修正計画に従って、コードを修正してください。

## 手順

1. Readツールで対象ファイルを読み込む
2. Editツールで修正を適用
3. 以下のコマンドを順番に実行:
   ```bash
   git add <修正したファイル>
   git commit -m "[PR Review] ({finding.number}) {finding.title}"
   git push origin {self._env_vars.get('FIX_BRANCH', 'HEAD')}
   git rev-parse HEAD
   ```
4. 最後に `git rev-parse HEAD` の出力（コミットハッシュ）を必ず報告

## 重要

- 必ず `git rev-parse HEAD` を実行してコミットハッシュを取得し、報告してください
- コミットハッシュは40文字の16進数文字列です（例: a1b2c3d4e5f6...）

## 出力形式

修正完了後、以下のJSON形式で報告してください:
```json
{{
  "file": "修正したファイルパス",
  "line": 修正した行番号,
  "line_end": 修正範囲の終了行番号,
  "commit_hash": "git rev-parse HEADの出力値"
}}
```
"""

        user_message = f"""
## 修正対象

**番号**: ({finding.number})
**タイトル**: {finding.title}
**ファイル**: {finding.source_file}
**行**: {finding.source_line}

## 問題の説明

{finding.description}

## 修正計画

{finding.fix_plan}

---

上記の修正計画に従って修正を適用し、コミット・プッシュしてください。
最後に必ず `git rev-parse HEAD` でコミットハッシュを取得して報告してください。
"""

        # Run with tools enabled for fix application
        result = self.claude_client.run_review(
            system_prompt=system_prompt,
            user_message=user_message,
            debug=self.debug,
            enable_tools=True,  # Phase 3: Enable tools for editing and committing
            env_vars=self._env_vars if self._env_vars else None,
        )

        if result.get("status") == "error":
            # Even on error, check if commit was created
            after_commit = self._get_latest_commit_for_finding(finding.number)
            if after_commit and after_commit != before_commit:
                return {
                    "success": True,
                    "commit_hash": after_commit,
                    "file": finding.source_file,
                    "line": finding.source_line,
                    "line_end": finding.source_line_end,
                }
            return {"success": False, "error": result.get("error")}

        # Extract fix result from findings
        findings_data = result.get("findings", [])
        if findings_data:
            fix_data = findings_data[0]
            commit_hash = fix_data.get("commit_hash")
            if commit_hash:
                return {
                    "success": True,
                    "commit_hash": commit_hash,
                    "file": fix_data.get("file", finding.source_file),
                    "line": fix_data.get("line", finding.source_line),
                    "line_end": fix_data.get("line_end", finding.source_line_end),
                }

        # Try to extract commit hash from text response
        text = result.get("text", "")

        # Pattern 1: Look for git rev-parse HEAD output (40-char hash on its own line)
        hash_patterns = [
            r'\b([a-f0-9]{40})\b',  # Full 40-char hash
            r'commit[_\s]*hash[:\s]*[`"\']?([a-f0-9]{7,40})[`"\']?',  # commit_hash: xxx
            r'rev-parse.*?([a-f0-9]{40})',  # After rev-parse
        ]

        for pattern in hash_patterns:
            hash_match = re.search(pattern, text, re.IGNORECASE)
            if hash_match:
                commit_hash = hash_match.group(1)
                return {
                    "success": True,
                    "commit_hash": commit_hash,
                    "file": finding.source_file,
                    "line": finding.source_line,
                    "line_end": finding.source_line_end,
                }

        # Fallback: Check git log for a commit matching this finding's pattern
        # This handles cases where Claude made the commit but didn't report the hash
        after_commit = self._get_latest_commit_for_finding(finding.number)
        if after_commit and after_commit != before_commit:
            if self.debug:
                console.print(f"[dim]Debug: Found commit via git log: {after_commit[:7]}[/dim]")
            return {
                "success": True,
                "commit_hash": after_commit,
                "file": finding.source_file,
                "line": finding.source_line,
                "line_end": finding.source_line_end,
            }

        # Last resort: Check if any commit/push operation was performed
        if "git push" in text.lower() or "git commit" in text.lower():
            # Try to get the latest commit hash directly
            try:
                git_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(self.config.project.unity_project_path),
                    capture_output=True,
                    text=True,
                )
                if git_result.returncode == 0:
                    commit_hash = git_result.stdout.strip()
                    # Only accept if it's a NEW commit (different from before)
                    if commit_hash and len(commit_hash) == 40 and commit_hash != before_commit:
                        return {
                            "success": True,
                            "commit_hash": commit_hash,
                            "file": finding.source_file,
                            "line": finding.source_line,
                            "line_end": finding.source_line_end,
                        }
            except Exception:
                pass

        return {"success": False, "error": "修正の適用またはコミットに失敗しました"}

    def _get_latest_commit_for_finding(self, finding_number: int) -> str | None:
        """Get the commit hash for a specific finding by searching git log.

        Args:
            finding_number: The finding number to search for

        Returns:
            Commit hash if found, None otherwise
        """
        import subprocess

        try:
            # Search for commit with message pattern "[PR Review] (N)"
            git_result = subprocess.run(
                [
                    "git", "log", "--oneline", "--grep",
                    f"\\[PR Review\\] ({finding_number})",
                    "-n", "1", "--format=%H",
                ],
                cwd=str(self.config.project.unity_project_path),
                capture_output=True,
                text=True,
            )
            if git_result.returncode == 0 and git_result.stdout.strip():
                return git_result.stdout.strip()
        except Exception:
            pass

        return None

    def run_compile_verification(self) -> bool:
        """Run compile verification phase using uLoopMCP.

        This phase verifies that the codebase compiles successfully.
        It can be used to check if suggested changes would break the build.

        Returns:
            True if compilation succeeded, False otherwise
        """
        if self.metadata is None or self.review_path is None:
            raise RuntimeError("Review not initialized")

        from src.unity import UnityCompiler

        console.print(Panel("コンパイル検証フェーズを開始", title="Phase: Compile Verification"))
        self.metadata.review_state.phases.compile_verification = Status.IN_PROGRESS
        self.metadata.review_state.current_phase = Phase.COMPILE_VERIFICATION
        self.metadata_handler.save_metadata(self.review_path, self.metadata)

        compiler = UnityCompiler(self.config.project.unity_project_path)

        console.print("  [cyan]Unityコンパイルを実行中...[/cyan]")
        result = compiler.compile(force_recompile=False)

        # Update compile results in metadata
        from datetime import datetime
        self.metadata.compile_results.last_check = datetime.now()
        self.metadata.compile_results.errors = [
            f"{e.file}:{e.line}: {e.message}" for e in result.errors
        ]
        self.metadata.compile_results.warnings = [
            f"{w.file}:{w.line}: {w.message}" for w in result.warnings
        ]

        if result.success:
            self.metadata.compile_results.status = Status.COMPLETED
            self.metadata.review_state.phases.compile_verification = Status.COMPLETED
            console.print(f"  [green]✓[/green] コンパイル成功")
            if result.warning_count > 0:
                console.print(f"    [yellow]警告: {result.warning_count} 件[/yellow]")
        else:
            self.metadata.compile_results.status = Status.FAILED
            self.metadata.review_state.phases.compile_verification = Status.FAILED
            console.print(f"  [red]✗[/red] コンパイル失敗")
            console.print(f"    [red]エラー: {result.error_count} 件[/red]")
            for error in result.errors[:5]:  # Show first 5 errors
                console.print(f"      - {error.file}:{error.line}: {error.message[:80]}")

        self.metadata_handler.save_metadata(self.review_path, self.metadata)

        return result.success

    def get_review_summary(self) -> dict[str, Any]:
        """Get a summary of the current review.

        Returns:
            Summary dictionary
        """
        if self.metadata is None:
            return {"error": "No review in progress"}

        return {
            "pr": {
                "number": self.metadata.pr.number,
                "repository": self.metadata.pr.repository,
            },
            "status": self.metadata.status.value,
            "current_phase": self.metadata.review_state.current_phase.value,
            "changed_files": len(self.metadata.changed_files),
            "explored_files": len(self.metadata.exploration_cache.explored_files),
            "findings": {
                "total": len(self.metadata.findings),
            },
            "compile_status": self.metadata.compile_results.status.value if self.metadata.compile_results else None,
        }

    def run_local_fix_application_phase(self) -> dict[str, Any]:
        """Run Phase 3 for local review: Apply fixes with local commits (no push).

        For each finding:
        1. Apply the fix using Claude with tools enabled (based on fix_plan)
        2. Commit locally (no push)

        Returns:
            Dict with results: applied, failed, skipped
        """
        if self.metadata is None or self.review_path is None:
            raise RuntimeError("Review not initialized")

        console.print(Panel("修正適用フェーズを開始（ローカル）", title="Phase: Local Fix Application"))
        self.metadata.review_state.phases.fix_application = Status.IN_PROGRESS
        self.metadata.review_state.current_phase = Phase.FIX_APPLICATION
        self.metadata_handler.save_metadata(self.review_path, self.metadata)

        results = {
            "applied": [],
            "failed": [],
            "skipped": [],
        }

        # Get report-only reviewers from config
        report_only_reviewers = self.config.review.report_only_reviewers

        # Process each finding sequentially
        for finding in self.metadata.findings:
            # Skip findings from report-only reviewers
            if finding.reviewer.value in report_only_reviewers:
                console.print(f"  [dim]スキップ[/dim]: ({finding.number}) {finding.title} - 報告のみ")
                results["skipped"].append(finding.id)
                continue

            if not finding.fix_plan:
                console.print(f"  [dim]スキップ[/dim]: ({finding.number}) {finding.title} - fix_planなし")
                results["skipped"].append(finding.id)
                continue

            console.print(f"  [cyan]修正中[/cyan]: ({finding.number}) {finding.title}")

            try:
                # Apply fix using Claude with tools and commit
                fix_result = self._apply_local_fix(finding)

                if fix_result.get("success"):
                    finding.file = fix_result.get("file", finding.source_file)
                    finding.line = fix_result.get("line", finding.source_line)
                    finding.line_end = fix_result.get("line_end", finding.source_line_end)
                    finding.commit_hash = fix_result.get("commit_hash")

                    results["applied"].append(finding.id)
                    if finding.commit_hash:
                        console.print(f"    [green]✓[/green] コミット: {finding.commit_hash[:7]}")
                    else:
                        console.print(f"    [green]✓[/green] 適用完了")
                else:
                    results["failed"].append(finding.id)
                    error = fix_result.get("error", "Unknown error")
                    console.print(f"    [red]✗[/red] 失敗: {error}")

            except Exception as e:
                results["failed"].append(finding.id)
                console.print(f"    [red]✗[/red] エラー: {e}")

            # Save progress after each finding
            self.metadata_handler.save_metadata(self.review_path, self.metadata)

        self.metadata.review_state.phases.fix_application = Status.COMPLETED
        self.metadata_handler.save_metadata(self.review_path, self.metadata)

        return results

    def _apply_local_fix(self, finding: Finding) -> dict[str, Any]:
        """Apply a single fix locally using Claude with tools, then commit.

        Args:
            finding: The finding to fix

        Returns:
            Dict with success, file, line, line_end, commit_hash, error
        """
        system_prompt = f"""あなたはUnity C#プロジェクトのコード修正アシスタントです。

## 役割

提供された修正計画に従って、コードを修正してください。

## 手順

1. Readツールで対象ファイルを読み込む
2. Editツールで修正を適用
3. 以下のコマンドでコミット:
   ```bash
   git add <修正したファイル>
   git commit -m "[PR Review] ({finding.number}) {finding.title}"
   git rev-parse HEAD
   ```

## 重要

- **プッシュは行わないでください**（git push は不要）
- 必ず `git rev-parse HEAD` を実行してコミットハッシュを取得し、報告してください

## 出力形式

修正完了後、以下のJSON形式で報告してください:
```json
{{
  "file": "修正したファイルパス",
  "line": 修正した行番号,
  "line_end": 修正範囲の終了行番号,
  "commit_hash": "git rev-parse HEADの出力値"
}}
```
"""

        user_message = f"""
## 修正対象

**番号**: ({finding.number})
**タイトル**: {finding.title}
**ファイル**: {finding.source_file}
**行**: {finding.source_line}

## 問題の説明

{finding.description}

## 修正計画

{finding.fix_plan}

---

上記の修正計画に従って修正を適用し、コミットしてください。
プッシュは不要です。
最後に必ず `git rev-parse HEAD` でコミットハッシュを取得して報告してください。
"""

        # Record commit before to detect if a new commit was made
        before_commit = self._get_latest_commit_for_finding(finding.number)

        # Run with tools enabled for fix application
        result = self.claude_client.run_review(
            system_prompt=system_prompt,
            user_message=user_message,
            debug=self.debug,
            enable_tools=True,  # Enable tools for editing
            env_vars=self._env_vars if self._env_vars else None,
        )

        if result.get("status") == "error":
            # Even on error, check if commit was created
            after_commit = self._get_latest_commit_for_finding(finding.number)
            if after_commit and after_commit != before_commit:
                return {
                    "success": True,
                    "commit_hash": after_commit,
                    "file": finding.source_file,
                    "line": finding.source_line,
                    "line_end": finding.source_line_end,
                }
            return {"success": False, "error": result.get("error")}

        # Extract fix result from findings
        findings_data = result.get("findings", [])
        if findings_data:
            fix_data = findings_data[0]
            commit_hash = fix_data.get("commit_hash")
            if commit_hash:
                return {
                    "success": True,
                    "commit_hash": commit_hash,
                    "file": fix_data.get("file", finding.source_file),
                    "line": fix_data.get("line", finding.source_line),
                    "line_end": fix_data.get("line_end", finding.source_line_end),
                }

        # Try to extract commit hash from text response
        import re
        text = result.get("text", "")

        hash_patterns = [
            r'\b([a-f0-9]{40})\b',
            r'commit[_\s]*hash[:\s]*[`"\']?([a-f0-9]{7,40})[`"\']?',
            r'rev-parse.*?([a-f0-9]{40})',
        ]

        for pattern in hash_patterns:
            hash_match = re.search(pattern, text, re.IGNORECASE)
            if hash_match:
                commit_hash = hash_match.group(1)
                return {
                    "success": True,
                    "commit_hash": commit_hash,
                    "file": finding.source_file,
                    "line": finding.source_line,
                    "line_end": finding.source_line_end,
                }

        # Fallback: Check git log for a commit matching this finding
        after_commit = self._get_latest_commit_for_finding(finding.number)
        if after_commit and after_commit != before_commit:
            return {
                "success": True,
                "commit_hash": after_commit,
                "file": finding.source_file,
                "line": finding.source_line,
                "line_end": finding.source_line_end,
            }

        # If Edit was used but no commit found, still consider partial success
        if "Edit" in text or "修正" in text:
            return {
                "success": True,
                "file": finding.source_file,
                "line": finding.source_line,
                "line_end": finding.source_line_end,
            }

        return {"success": False, "error": "修正の適用に失敗しました"}

    def generate_markdown_report(self) -> Path:
        """Generate a markdown report of the review findings.

        Returns:
            Path to the generated report file
        """
        if self.metadata is None or self.review_path is None:
            raise RuntimeError("Review not initialized")

        report_lines = []

        # Header
        report_lines.append(f"# レビューレポート")
        report_lines.append("")
        report_lines.append(f"**ブランチ**: {self.metadata.pr.head_branch} → {self.metadata.pr.base_branch}")
        report_lines.append(f"**レビュー日時**: {self.metadata.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"**変更ファイル数**: {len(self.metadata.changed_files)}")
        report_lines.append(f"**検出した問題**: {len(self.metadata.findings)} 件")
        report_lines.append("")

        # Summary table
        report_lines.append("## サマリー")
        report_lines.append("")
        report_lines.append("| # | レビュワー | タイトル | ファイル | 行 | 状態 |")
        report_lines.append("|---|-----------|---------|---------|-----|------|")

        for finding in self.metadata.findings:
            number = f"({finding.number})" if finding.number else "-"
            status = "✓ 適用済" if finding.file else "⚠ 未適用"
            line = str(finding.source_line) if finding.source_line else "-"
            file_short = Path(finding.source_file).name if finding.source_file else "-"
            report_lines.append(
                f"| {number} | {finding.reviewer.value} | {finding.title} | {file_short} | {line} | {status} |"
            )

        report_lines.append("")

        # Detailed findings
        report_lines.append("## 詳細")
        report_lines.append("")

        for finding in self.metadata.findings:
            number = f"({finding.number})" if finding.number else ""
            report_lines.append(f"### {number} {finding.title}")
            report_lines.append("")
            report_lines.append(f"**レビュワー**: {finding.reviewer.value}")
            report_lines.append(f"**ファイル**: `{finding.source_file}`")
            if finding.source_line:
                line_info = f"L{finding.source_line}"
                if finding.source_line_end and finding.source_line_end != finding.source_line:
                    line_info += f"-{finding.source_line_end}"
                report_lines.append(f"**行**: {line_info}")
            report_lines.append("")

            if finding.description:
                report_lines.append("#### 説明")
                report_lines.append("")
                report_lines.append(finding.description)
                report_lines.append("")

            if finding.scenario:
                report_lines.append("#### 発生シナリオ")
                report_lines.append("")
                report_lines.append(finding.scenario)
                report_lines.append("")

            if finding.fix_plan:
                report_lines.append("#### 修正計画")
                report_lines.append("")
                report_lines.append(finding.fix_plan)
                report_lines.append("")

            report_lines.append("---")
            report_lines.append("")

        # Write report
        report_path = self.review_path / "report.md"
        report_path.write_text("\n".join(report_lines), encoding="utf-8")

        return report_path
