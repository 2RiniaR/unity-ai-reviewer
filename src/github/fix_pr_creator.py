"""Create a fix PR with all committed fixes collected.

In the new 3-phase architecture:
- Phase 1: Parallel review (analysis only)
- Phase 2: Create draft PR with summary table (this module)
- Phase 3: Sequential fix application (commits added after PR creation)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

from src.github.client import GitHubClient, PullRequest
from src.github.git_operations import GitOperations
from src.models import Finding, Metadata

console = Console()


def expand_template(
    template: str,
    branch: str = "",
    timestamp: str = "",
    number: int = 0,
    title: str = "",
) -> str:
    """Expand a template string with placeholders.

    Placeholders:
        ($Branch) - target PR's branch name
        ($Timestamp) - timestamp
        ($Number) - target PR's number
        ($Title) - target PR's title

    Args:
        template: Template string with placeholders
        branch: Branch name
        timestamp: Timestamp string
        number: PR number
        title: PR title

    Returns:
        Expanded string
    """
    result = template
    result = result.replace("($Branch)", branch)
    result = result.replace("($Timestamp)", timestamp)
    result = result.replace("($Number)", str(number))
    result = result.replace("($Title)", title)
    return result


@dataclass
class FixPRResult:
    """Result of creating a fix PR."""

    success: bool
    fix_pr_url: str | None = None
    fix_pr_number: int | None = None
    branch_name: str | None = None
    applied_findings: list[str] = field(default_factory=list)
    failed_findings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    is_draft: bool = False


class FixPRCreator:
    """Creates a fix PR in the 3-phase architecture.

    Phase 2 responsibilities:
    1. Create a draft PR with summary table (before fixes are applied)
    2. Post link comment on the original PR

    Phase 3 responsibilities (via update methods):
    3. Update PR body with commit hashes as fixes are applied
    4. Post explanation comments for each fix

    The PR body includes a summary table with commit links for each fix.
    """

    def __init__(
        self,
        github_client: GitHubClient,
        project_path: Path,
        debug: bool = False,
        pr_title_template: str = "[自動修正] #($Number)「($Title)」",
    ) -> None:
        """Initialize the fix PR creator.

        Args:
            github_client: GitHub client for API operations
            project_path: Path to the project (Unity project root)
            debug: Enable debug output
            pr_title_template: Template for fix PR title
        """
        self.github_client = github_client
        self.project_path = project_path
        self.debug = debug
        self.pr_title_template = pr_title_template
        self.git = GitOperations(project_path)
        self._repo_base: str | None = None  # Set during create_fix_pr

    def create_fix_pr(
        self,
        original_pr_number: int,
        metadata: Metadata,
        as_draft: bool = True,
    ) -> FixPRResult:
        """Create a fix PR (Phase 2: before fixes are applied).

        In the new 3-phase architecture, this creates a draft PR with the summary
        table before any fixes are applied. Fixes will be committed in Phase 3.

        Args:
            original_pr_number: The original PR number being reviewed
            metadata: Review metadata containing findings (may not have commit_hash yet)
            as_draft: Whether to create as draft PR (default: True for Phase 2)

        Returns:
            FixPRResult with PR details
        """
        result = FixPRResult(success=False, is_draft=as_draft)
        original_branch: str | None = None
        stashed = False

        try:
            # 1. Get original PR info
            original_pr = self.github_client.get_pull_request(original_pr_number)
            is_merged = original_pr.state == "MERGED"

            # Extract repo URL base for commit links
            import re
            repo_base_match = re.match(r'(https://github\.com/[^/]+/[^/]+)', original_pr.url)
            self._repo_base = repo_base_match.group(1) if repo_base_match else None

            if self.debug:
                print(f"[DEBUG] Original PR: {original_pr.head_branch} -> {original_pr.base_branch}")
                print(f"[DEBUG] PR state: {original_pr.state}")
                print(f"[DEBUG] Repo base: {self._repo_base}")

            # Determine the target branch for the fix PR
            target_branch = original_pr.base_branch if is_merged else original_pr.head_branch

            if self.debug:
                print(f"[DEBUG] Fix PR target: {target_branch}")

            # 2. Get all findings (Phase 2: they don't have commit_hash yet)
            all_findings = metadata.findings

            if self.debug:
                print(f"[DEBUG] Total findings: {len(all_findings)}")

            if not all_findings:
                result.errors.append("No findings to include")
                return result

            # 3. Save current state
            original_branch = self.git.get_current_branch()
            if self.git.has_uncommitted_changes():
                if self.debug:
                    print("[DEBUG] Stashing uncommitted changes")
                self.git.stash_push("PR Review: temporary stash before fix PR creation")
                stashed = True

            # 4. Create initial commit for draft PR (Phase 2: no fixes yet)
            current_branch = self.git.get_current_branch()
            result.branch_name = current_branch

            # Create an empty commit to enable PR creation
            if not self._create_initial_commit(original_pr_number, len(all_findings)):
                result.errors.append("Failed to create initial commit")
                self._restore_branch(original_branch, stashed)
                return result

            if not self.git.push(current_branch):
                result.errors.append("Failed to push branch")
                self._restore_branch(original_branch, stashed)
                return result

            if self.debug:
                print("[DEBUG] Branch pushed to remote")

            # 5. Create fix PR (as draft for Phase 2)
            pr_title = expand_template(
                self.pr_title_template,
                branch=original_pr.head_branch,
                number=original_pr_number,
                title=original_pr.title,
            )
            pr_body = self._build_pr_body(
                original_pr_number, original_pr.url, all_findings, is_merged
            )

            try:
                pr_result = self.github_client.create_pull_request(
                    title=pr_title,
                    body=pr_body,
                    head=current_branch,
                    base=target_branch,
                    draft=as_draft,
                )
                result.fix_pr_number = pr_result["number"]
                result.fix_pr_url = pr_result["url"]

                if self.debug:
                    print(f"[DEBUG] Fix PR created (draft={as_draft}): {result.fix_pr_url}")

            except Exception as e:
                result.errors.append(f"Failed to create PR: {e}")
                self._restore_branch(original_branch, stashed)
                return result

            # 6. Link comment on original PR is now handled by ProgressCommentManager in main.py
            # Note: Explanation comments are posted in Phase 3 after each fix

            # 7. Restore original branch
            self._restore_branch(original_branch, stashed)

            result.success = True
            return result

        except Exception as e:
            result.errors.append(f"Unexpected error: {e}")
            if original_branch:
                self._restore_branch(original_branch, stashed)
            return result

    def create_fix_pr_after_fixes(
        self,
        original_pr_number: int,
        metadata: Metadata,
    ) -> FixPRResult:
        """Create a fix PR after all fixes are applied (legacy behavior).

        This method creates a non-draft PR after fixes are committed.
        Use this if you prefer the old workflow where PR is created after fixes.

        Args:
            original_pr_number: The original PR number being reviewed
            metadata: Review metadata containing findings with commit_hash

        Returns:
            FixPRResult with PR details
        """
        result = FixPRResult(success=False, is_draft=False)
        original_branch: str | None = None
        stashed = False

        try:
            # 1. Get original PR info
            original_pr = self.github_client.get_pull_request(original_pr_number)
            is_merged = original_pr.state == "MERGED"

            if self.debug:
                print(f"[DEBUG] Original PR: {original_pr.head_branch} -> {original_pr.base_branch}")
                print(f"[DEBUG] PR state: {original_pr.state}")

            # Determine the target branch for the fix PR
            target_branch = original_pr.base_branch if is_merged else original_pr.head_branch

            if self.debug:
                print(f"[DEBUG] Fix PR target: {target_branch}")

            # 2. Filter findings with commit_hash (already fixed and committed)
            findings_with_commits = [
                f for f in metadata.findings
                if f.commit_hash
            ]

            if self.debug:
                print(f"[DEBUG] Total findings: {len(metadata.findings)}")
                print(f"[DEBUG] Findings with commit_hash: {len(findings_with_commits)}")

            if not findings_with_commits:
                result.errors.append("No findings with commits to include")
                return result

            # Mark all as applied since they're already committed
            for f in findings_with_commits:
                result.applied_findings.append(f.id)

            # 3. Save current state
            original_branch = self.git.get_current_branch()
            if self.git.has_uncommitted_changes():
                if self.debug:
                    print("[DEBUG] Stashing uncommitted changes")
                self.git.stash_push("PR Review: temporary stash before fix PR creation")
                stashed = True

            # 4. Push current branch to remote
            current_branch = self.git.get_current_branch()
            result.branch_name = current_branch

            if not self.git.push(current_branch):
                result.errors.append("Failed to push branch")
                self._restore_branch(original_branch, stashed)
                return result

            if self.debug:
                print("[DEBUG] Branch pushed to remote")

            # 5. Create fix PR (not draft)
            pr_title = expand_template(
                self.pr_title_template,
                branch=original_pr.head_branch,
                number=original_pr_number,
                title=original_pr.title,
            )
            pr_body = self._build_pr_body(
                original_pr_number, original_pr.url, findings_with_commits, is_merged
            )

            try:
                pr_result = self.github_client.create_pull_request(
                    title=pr_title,
                    body=pr_body,
                    head=current_branch,
                    base=target_branch,
                    draft=False,
                )
                result.fix_pr_number = pr_result["number"]
                result.fix_pr_url = pr_result["url"]

                if self.debug:
                    print(f"[DEBUG] Fix PR created: {result.fix_pr_url}")

            except Exception as e:
                result.errors.append(f"Failed to create PR: {e}")
                self._restore_branch(original_branch, stashed)
                return result

            # 6. Post explanation comments on fix PR
            self._post_explanation_comments(
                result.fix_pr_number, original_pr, findings_with_commits
            )

            if self.debug:
                print("[DEBUG] Explanation comments posted")

            # 7. Post link comment on original PR (with author mention)
            self._post_link_comment(
                original_pr_number,
                result.fix_pr_url,
                len(result.applied_findings),
                original_pr.author,
            )

            if self.debug:
                print("[DEBUG] Link comment posted on original PR")

            # 8. Restore original branch
            self._restore_branch(original_branch, stashed)

            result.success = True
            return result

        except Exception as e:
            result.errors.append(f"Unexpected error: {e}")
            if original_branch:
                self._restore_branch(original_branch, stashed)
            return result

    def _build_commit_message(
        self,
        original_pr_number: int,
        findings: list[Finding],
    ) -> str:
        """Build commit message for the fix commit.

        Args:
            original_pr_number: Original PR number
            findings: List of applied findings

        Returns:
            Commit message string
        """
        lines = [
            f"Apply PR review suggestions from PR #{original_pr_number}",
            "",
            f"Applied {len(findings)} verified fixes:",
            "",
        ]

        for finding in findings:
            lines.append(f"- [{finding.id}] {finding.title} ({finding.file})")

        lines.extend([
            "",
            "🤖 Generated with PR Reviewer",
        ])

        return "\n".join(lines)

    def _build_pr_body(
        self,
        original_pr_number: int,
        original_pr_url: str,
        findings: list[Finding],
        is_merged: bool = False,
    ) -> str:
        """Build PR body for the fix PR.

        Args:
            original_pr_number: Original PR number
            original_pr_url: URL of the original PR
            findings: List of findings (may or may not have commit_hash yet)
            is_merged: Whether the original PR was merged

        Returns:
            PR body markdown string
        """
        # Extract repo URL base for commit links (e.g., https://github.com/owner/repo)
        import re
        repo_base_match = re.match(r'(https://github\.com/[^/]+/[^/]+)', original_pr_url)
        repo_base = repo_base_match.group(1) if repo_base_match else None

        if is_merged:
            description = (
                f"このPRは [PR #{original_pr_number}]({original_pr_url}) "
                f"（マージ済み）のレビュー指摘を自動修正したものです。"
            )
        else:
            description = (
                f"このPRは [PR #{original_pr_number}]({original_pr_url}) "
                f"のレビュー指摘を自動修正したものです。"
            )

        # Count applied vs pending
        applied_count = len([f for f in findings if f.commit_hash])
        pending_count = len([f for f in findings if not f.commit_hash])

        lines = [
            "## 🔧 自動修正PR",
            "",
            description,
            "",
        ]

        # Add status indicator
        if pending_count > 0:
            lines.extend([
                f"**ステータス**: 🔄 修正適用中 ({applied_count}/{len(findings)} 完了)",
                "",
            ])
        else:
            lines.extend([
                f"**ステータス**: ✅ 全修正完了 ({applied_count} 件)",
                "",
            ])

        lines.extend([
            "### 修正一覧",
            "",
            "| # | ステータス | レビュアー | タイトル | 修正内容 |",
            "|---|------------|-----------|---------|----------|",
        ])

        for finding in findings:
            reviewer = finding.reviewer.display_name
            # Use source_file if file (fix location) is not yet set
            file_path = finding.file or finding.source_file
            file_name = file_path.split("/")[-1] if file_path else "N/A"

            # Escape pipe characters in title
            title_text = finding.title.replace("|", "\\|")
            # Format: file name + line break + title (with optional link)
            if finding.comment_url:
                title_cell = f"`{file_name}`<br>[{title_text}]({finding.comment_url})"
            else:
                title_cell = f"`{file_name}`<br>{title_text}"

            # fix_summary without truncation
            fix_summary = finding.fix_summary or "-"
            fix_summary = fix_summary.replace("|", "\\|")

            if finding.commit_hash:
                # Create commit link
                short_hash = finding.commit_hash[:7]
                if repo_base:
                    commit_link = f"[`{short_hash}`]({repo_base}/commit/{finding.commit_hash})"
                else:
                    commit_link = f"`{short_hash}`"
                status = f"✅ {commit_link}"
            else:
                status = "⏳ 待機中"

            lines.append(
                f"| ({finding.number}) | {status} | {reviewer} | {title_cell} | {fix_summary} |"
            )

        lines.extend([
            "",
            "### 使い方",
            "",
            "1. 各修正のコメントを確認してください",
            "2. 問題なければこのPRをマージしてください",
            "",
            "---",
            "",
            "🤖 *Generated with [PR Reviewer](https://github.com/anthropics/claude-code)*",
        ])

        return "\n".join(lines)

    def _post_explanation_comments(
        self,
        fix_pr_number: int,
        original_pr: PullRequest,
        findings: list[Finding],
    ) -> None:
        """Post explanation comments on the fix PR.

        Each comment explains why the fix was applied.

        Args:
            fix_pr_number: Fix PR number
            original_pr: Original PR info
            findings: List of findings with commit_hash
        """
        # Get the fix PR info (to get the commit SHA)
        fix_pr = self.github_client.get_pull_request(fix_pr_number)

        # Get commentable lines from the Fix PR's diff
        commentable_lines = self.github_client.get_commentable_lines(fix_pr_number)

        for i, finding in enumerate(findings, 1):
            try:
                comment_body = self._format_explanation_comment(finding, number=i)

                line_end = finding.line_end or finding.line
                start_line = finding.line if finding.line != line_end else None

                if self.debug:
                    file_commentable = commentable_lines.get(finding.file, set())
                    print(f"[DEBUG] Posting comment ({i}) for {finding.id}: {finding.file}")
                    print(f"[DEBUG]   Lines: {finding.line}-{line_end}")
                    if line_end not in file_commentable:
                        print(f"[DEBUG]   WARNING: Line {line_end} not in commentable lines!")
                        available = sorted(file_commentable) if file_commentable else []
                        print(f"[DEBUG]   Available: {available[:20]}{'...' if len(available) > 20 else ''}")

                self.github_client.create_review_comment(
                    pr_number=fix_pr_number,
                    body=comment_body,
                    commit_sha=fix_pr.head_sha,
                    path=finding.file,
                    line=line_end,
                    start_line=start_line,
                )

            except Exception as e:
                if self.debug:
                    print(f"[DEBUG] Failed to post comment for {finding.id}")
                    print(f"[DEBUG]   File: {finding.file}, Line: {line_end}, Start: {start_line}")
                    print(f"[DEBUG]   Error: {e}")

    def _format_explanation_comment(
        self,
        finding: Finding,
        number: int,
        repo_base: str | None = None,
    ) -> str:
        """Format an explanation comment for a finding.

        Args:
            finding: The finding with commit_hash
            number: The finding number (1-indexed)
            repo_base: Base URL for repository (e.g., https://github.com/owner/repo)

        Returns:
            Formatted markdown comment
        """
        lines = [
            f"## ({finding.number}) 【{finding.reviewer.display_name}】{finding.title}",
            "",
            finding.description,
        ]

        # Add fix_summary outside of <details> (not collapsed)
        if finding.fix_summary:
            lines.extend([
                "",
                f"**修正方法**: {finding.fix_summary}",
            ])

        # Add commit link right after fix_summary (outside of <details>)
        if finding.commit_hash:
            if repo_base:
                commit_link = f"[修正内容はここから確認できます]({repo_base}/commit/{finding.commit_hash})"
            else:
                commit_link = f"コミット: `{finding.commit_hash}`"
            lines.extend([
                "",
                f"🔧 {commit_link}",
            ])

        # Add details section with scenario only
        if finding.scenario:
            lines.extend([
                "",
                "<details>",
                "<summary>詳細</summary>",
                "",
                "### 問題が発生するシナリオ",
                "",
                finding.scenario,
                "",
                "</details>",
            ])

        return "\n".join(lines)

    def _post_link_comment(
        self,
        original_pr_number: int,
        fix_pr_url: str,
        applied_count: int,
        author: str,
    ) -> None:
        """Post a comment on the original PR linking to the fix PR (after fixes applied).

        Args:
            original_pr_number: Original PR number
            fix_pr_url: URL of the fix PR
            applied_count: Number of fixes applied
            author: GitHub username of the PR author
        """
        comment = f"""## 🔧 自動修正PRを作成しました

@{author} {applied_count} 件の修正を適用したPRを作成しました。内容を確認し、問題なければマージをお願いします。

👉 **{fix_pr_url}**

各修正はレビューコメントで確認できます。

---

🤖 *Generated with [PR Reviewer](https://github.com/anthropics/claude-code)*
"""

        try:
            self.github_client.create_issue_comment(original_pr_number, comment)
        except Exception as e:
            if self.debug:
                print(f"[DEBUG] Failed to post link comment: {e}")

    def _post_link_comment_draft(
        self,
        original_pr_number: int,
        fix_pr_url: str,
        total_count: int,
        pending_count: int,
        author: str,
    ) -> None:
        """Post a comment on the original PR linking to the draft fix PR (Phase 2).

        Args:
            original_pr_number: Original PR number
            fix_pr_url: URL of the draft fix PR
            total_count: Total number of findings
            pending_count: Number of pending fixes
            author: GitHub username of the PR author
        """
        if pending_count > 0:
            status = f"🔄 {total_count} 件の修正を適用中..."
        else:
            status = f"✅ {total_count} 件の修正を完了しました"

        comment = f"""## 🔧 自動修正PR（ドラフト）を作成しました

@{author} レビュー指摘に基づく修正PRを作成しました。

{status}

👉 **{fix_pr_url}**

修正の適用状況はPRのbodyで確認できます。全ての修正が完了したら、内容を確認してマージしてください。

---

🤖 *Generated with [PR Reviewer](https://github.com/anthropics/claude-code)*
"""

        try:
            self.github_client.create_issue_comment(original_pr_number, comment)
        except Exception as e:
            if self.debug:
                print(f"[DEBUG] Failed to post link comment: {e}")

    def post_single_explanation_comment(
        self,
        fix_pr_number: int,
        finding: Finding,
    ) -> str | None:
        """Post a single explanation comment for a finding (Phase 3).

        Called after each fix is committed during Phase 3.
        Always attempts to post a comment, even if the fix failed.

        Args:
            fix_pr_number: Fix PR number
            finding: The finding that was just fixed

        Returns:
            Comment URL if posted successfully, None otherwise
        """
        try:
            # Get the fix PR info
            fix_pr = self.github_client.get_pull_request(fix_pr_number)

            comment_body = self._format_explanation_comment(
                finding,
                number=finding.number or 0,
                repo_base=self._repo_base,
            )

            # Determine file and lines for the comment
            # Prefer fix location (file/line), fall back to source location
            file_path = finding.file or finding.source_file
            line = finding.line or finding.source_line
            line_end = finding.line_end or finding.source_line_end or line

            # Get commentable lines to find a valid location
            commentable_lines = self.github_client.get_commentable_lines(fix_pr_number)

            # If no file_path or invalid line, fall back to any commentable location
            if not file_path or not line or line <= 0:
                if self.debug:
                    print(f"[DEBUG] ({finding.number}): No valid file/line, searching for fallback location")
                    print(f"[DEBUG]   finding.file={finding.file}, finding.source_file={finding.source_file}")
                    print(f"[DEBUG]   finding.line={finding.line}, finding.source_line={finding.source_line}")

                # Find any commentable location as fallback
                fallback = self._find_any_commentable_location(commentable_lines)
                if fallback:
                    file_path, line_end = fallback
                    line = line_end
                    if self.debug:
                        print(f"[DEBUG]   Using fallback location: {file_path}:{line_end}")
                else:
                    if self.debug:
                        print(f"[DEBUG] Skipping comment for ({finding.number}): no commentable lines in diff")
                    return False

            start_line = line if line != line_end else None

            if self.debug:
                print(f"[DEBUG] Posting comment ({finding.number}) for {finding.id}: {file_path}")
                print(f"[DEBUG]   Lines: {line}-{line_end}, commit: {finding.commit_hash or 'N/A'}")

            file_commentable = commentable_lines.get(file_path, set())

            if line_end not in file_commentable:
                if self.debug:
                    print(f"[DEBUG] WARNING: Line {line_end} not in diff for {file_path}")
                    available = sorted(file_commentable) if file_commentable else []
                    print(f"[DEBUG]   Commentable lines: {available[:20]}{'...' if len(available) > 20 else ''}")

                # Try to find a nearby commentable line in the same file first
                if file_commentable:
                    closest = min(file_commentable, key=lambda x: abs(x - line_end))
                    if self.debug:
                        print(f"[DEBUG]   Using line {closest} in same file")
                    line_end = closest
                    line = closest
                    start_line = None
                else:
                    # Fall back to any commentable location
                    fallback = self._find_any_commentable_location(commentable_lines)
                    if fallback:
                        file_path, line_end = fallback
                        line = line_end
                        start_line = None
                        if self.debug:
                            print(f"[DEBUG]   Using fallback location: {file_path}:{line_end}")
                    else:
                        if self.debug:
                            print(f"[DEBUG] Skipping comment: no commentable lines found")
                        return False

            # Use finding's commit_hash if available, otherwise fall back to PR head
            commit_sha = finding.commit_hash or fix_pr.head_sha

            # Retry logic for GitHub API (may take time to index new commits)
            import time
            max_retries = 3
            retry_delay = 1.0
            last_error = None

            for attempt in range(max_retries):
                try:
                    comment_result = self.github_client.create_review_comment(
                        pr_number=fix_pr_number,
                        body=comment_body,
                        commit_sha=commit_sha,
                        path=file_path,
                        line=line_end,
                        start_line=start_line,
                    )

                    comment_url = comment_result.get("html_url")
                    if self.debug:
                        print(f"[DEBUG] Comment posted successfully for ({finding.number})")
                        if comment_url:
                            print(f"[DEBUG]   URL: {comment_url}")

                    return comment_url

                except Exception as retry_error:
                    last_error = retry_error
                    if attempt < max_retries - 1:
                        if self.debug:
                            print(f"[DEBUG] Comment post attempt {attempt + 1} failed, retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    else:
                        raise last_error

        except Exception as e:
            console.print(f"[yellow]    警告: ({finding.number}) のコメント投稿に失敗[/yellow]")
            if self.debug:
                print(f"[DEBUG] Failed to post comment for ({finding.number}) {finding.id}")
                print(f"[DEBUG]   file={finding.file or finding.source_file}")
                print(f"[DEBUG]   line={finding.line or finding.source_line}")
                print(f"[DEBUG]   Error: {e}")
            return None

    def update_pr_body(
        self,
        fix_pr_number: int,
        original_pr_number: int,
        metadata: Metadata,
    ) -> bool:
        """Update the fix PR body to reflect current fix status.

        Called after fixes are applied to update the summary table.

        Args:
            fix_pr_number: Fix PR number
            original_pr_number: Original PR number
            metadata: Updated metadata with commit_hash

        Returns:
            True if update was successful
        """
        try:
            original_pr = self.github_client.get_pull_request(original_pr_number)
            is_merged = original_pr.state == "MERGED"

            new_body = self._build_pr_body(
                original_pr_number,
                original_pr.url,
                metadata.findings,
                is_merged,
            )

            self.github_client.update_pull_request(
                fix_pr_number,
                body=new_body,
            )

            if self.debug:
                print(f"[DEBUG] Updated PR #{fix_pr_number} body")

            return True

        except Exception as e:
            if self.debug:
                print(f"[DEBUG] Failed to update PR body: {e}")
            return False

    def mark_pr_ready(self, fix_pr_number: int) -> bool:
        """Mark the draft PR as ready for review.

        Called after Phase 3 completes to convert draft to open PR.

        Args:
            fix_pr_number: Fix PR number

        Returns:
            True if successful
        """
        try:
            result = self.github_client.mark_pr_ready(fix_pr_number)

            if self.debug:
                print(f"[DEBUG] Marked PR #{fix_pr_number} as ready: {result}")

            return result

        except Exception as e:
            if self.debug:
                print(f"[DEBUG] Failed to mark PR as ready: {e}")
            return False

    def _create_initial_commit(
        self,
        original_pr_number: int,
        findings_count: int,
    ) -> bool:
        """Create an initial empty commit to enable draft PR creation.

        Args:
            original_pr_number: Original PR number
            findings_count: Number of findings to be fixed

        Returns:
            True if commit was created successfully
        """
        import subprocess

        commit_message = f"""[PR Review] PR #{original_pr_number} の自動修正を開始

このPRには {findings_count} 件の修正が適用される予定です。
修正は順次コミットされます。

🤖 Generated with PR Reviewer
"""

        try:
            # Create empty commit
            result = subprocess.run(
                ["git", "commit", "--allow-empty", "-m", commit_message],
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                if self.debug:
                    print(f"[DEBUG] Failed to create initial commit: {result.stderr}")
                return False

            if self.debug:
                print("[DEBUG] Created initial empty commit")

            return True

        except Exception as e:
            if self.debug:
                print(f"[DEBUG] Exception creating initial commit: {e}")
            return False

    def _find_any_commentable_location(
        self,
        commentable_lines: dict[str, set[int]],
    ) -> tuple[str, int] | None:
        """Find any commentable location in the diff as a fallback.

        Args:
            commentable_lines: Dict mapping file_path -> set of line numbers

        Returns:
            Tuple of (file_path, line_number) or None if no location found
        """
        for file_path, lines in commentable_lines.items():
            if lines:
                # Return the first available line in the first file with lines
                return (file_path, min(lines))
        return None

    def _cleanup(
        self,
        original_branch: str | None,
        fix_branch: str | None,
        stashed: bool,
    ) -> None:
        """Cleanup on failure: restore branch and optionally delete fix branch.

        Args:
            original_branch: Branch to return to
            fix_branch: Fix branch to delete (if not pushed)
            stashed: Whether changes were stashed
        """
        if original_branch:
            self.git.checkout_branch(original_branch)

        if fix_branch:
            self.git.delete_branch(fix_branch, force=True)

        if stashed:
            self.git.stash_pop()

    def _restore_branch(self, original_branch: str | None, stashed: bool) -> None:
        """Restore the original branch after successful operation.

        Args:
            original_branch: Branch to return to
            stashed: Whether changes were stashed
        """
        if original_branch:
            self.git.checkout_branch(original_branch)

        if stashed:
            self.git.stash_pop()
