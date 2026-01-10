"""Progress comment management for PR review workflow.

Manages a single progress comment on the original PR that gets updated
as the review workflow progresses through phases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.github.client import GitHubClient


class ProgressCommentManager:
    """Manages the progress comment on the original PR.

    This class handles posting and updating a single comment on the original PR
    to track the review workflow progress:
    - Phase 1 start: Post initial comment
    - Phase 1 complete (no findings): Update to show "no issues found"
    - Phase 2 complete: Update to show Fix PR link
    - Phase 3 complete: Update to show completion status
    """

    def __init__(
        self,
        github_client: GitHubClient,
        original_pr_number: int,
        author: str,
        debug: bool = False,
    ) -> None:
        """Initialize the progress comment manager.

        Args:
            github_client: GitHub client for API operations
            original_pr_number: The original PR number being reviewed
            author: GitHub username of the PR author (for mention)
            debug: Enable debug output
        """
        self.github_client = github_client
        self.original_pr_number = original_pr_number
        self.author = author
        self.debug = debug
        self.comment_id: int | None = None

    def post_phase1_start(self) -> int | None:
        """Post initial comment when Phase 1 starts.

        Returns:
            Comment ID if successful, None otherwise
        """
        body = self._build_phase1_start_body()
        try:
            result = self.github_client.create_issue_comment(
                self.original_pr_number, body
            )
            self.comment_id = result.get("id")
            if self.debug:
                print(f"[DEBUG] Posted Phase 1 start comment, id={self.comment_id}")
            return self.comment_id
        except Exception as e:
            if self.debug:
                print(f"[DEBUG] Failed to post Phase 1 start comment: {e}")
            return None

    def update_phase1_no_findings(self) -> bool:
        """Update comment when Phase 1 completes with no findings.

        Returns:
            True if successful, False otherwise
        """
        body = self._build_no_findings_body()
        return self._update_or_create(body, "Phase 1 no findings")

    def update_phase2_complete(
        self,
        fix_pr_url: str,
        fix_pr_number: int,
        total_findings: int,
    ) -> bool:
        """Update comment when Phase 2 creates the fix PR.

        Args:
            fix_pr_url: URL of the fix PR
            fix_pr_number: Fix PR number
            total_findings: Total number of findings

        Returns:
            True if successful, False otherwise
        """
        body = self._build_phase2_complete_body(
            fix_pr_url, fix_pr_number, total_findings
        )
        return self._update_or_create(body, "Phase 2 complete")

    def update_phase3_complete(
        self,
        fix_pr_url: str,
        fix_pr_number: int,
        applied_count: int,
        failed_count: int,
        skipped_count: int,
    ) -> bool:
        """Update comment when Phase 3 completes.

        Args:
            fix_pr_url: URL of the fix PR
            fix_pr_number: Fix PR number
            applied_count: Number of fixes successfully applied
            failed_count: Number of fixes that failed
            skipped_count: Number of fixes that were skipped

        Returns:
            True if successful, False otherwise
        """
        body = self._build_phase3_complete_body(
            fix_pr_url, fix_pr_number,
            applied_count, failed_count, skipped_count
        )
        return self._update_or_create(body, "Phase 3 complete")

    def _update_or_create(self, body: str, phase_name: str) -> bool:
        """Update existing comment or create new one as fallback.

        Args:
            body: Comment body
            phase_name: Name of the phase (for debug logging)

        Returns:
            True if successful, False otherwise
        """
        if self.comment_id:
            try:
                self.github_client.update_issue_comment(self.comment_id, body)
                if self.debug:
                    print(f"[DEBUG] Updated comment ({phase_name}), id={self.comment_id}")
                return True
            except Exception as e:
                if self.debug:
                    print(f"[DEBUG] Failed to update comment ({phase_name}): {e}")
                # Fall through to create new comment

        # Fallback: create new comment
        try:
            result = self.github_client.create_issue_comment(
                self.original_pr_number, body
            )
            self.comment_id = result.get("id")
            if self.debug:
                print(f"[DEBUG] Created new comment ({phase_name}), id={self.comment_id}")
            return True
        except Exception as e:
            if self.debug:
                print(f"[DEBUG] Failed to create comment ({phase_name}): {e}")
            return False

    def _build_phase1_start_body(self) -> str:
        """Build comment body for Phase 1 start."""
        return f"""## 🔍 自動レビューを開始しました

@{self.author} PRのレビューを開始しました。問題が見つかった場合は、修正PRを自動作成します。

**ステータス**: 🔄 分析中...

---

🤖 *Generated with [PR Reviewer](https://github.com/anthropics/claude-code)*
"""

    def _build_no_findings_body(self) -> str:
        """Build comment body when no findings."""
        return f"""## ✅ 自動レビュー完了

@{self.author} PRをレビューしましたが、問題は見つかりませんでした。

**ステータス**: ✅ 完了（問題なし）

---

🤖 *Generated with [PR Reviewer](https://github.com/anthropics/claude-code)*
"""

    def _build_phase2_complete_body(
        self,
        fix_pr_url: str,
        fix_pr_number: int,
        total_findings: int,
    ) -> str:
        """Build comment body for Phase 2 complete."""
        return f"""## 🔧 自動修正PRを作成しました

@{self.author} {total_findings} 件の問題を検出し、修正PRを作成しました。

**ステータス**: 🔄 修正適用中...

👉 **{fix_pr_url}**

修正の適用状況はPRのbodyで確認できます。

---

🤖 *Generated with [PR Reviewer](https://github.com/anthropics/claude-code)*
"""

    def _build_phase3_complete_body(
        self,
        fix_pr_url: str,
        fix_pr_number: int,
        applied_count: int,
        failed_count: int,
        skipped_count: int,
    ) -> str:
        """Build comment body for Phase 3 complete."""
        total = applied_count + failed_count + skipped_count

        if failed_count > 0:
            status = f"⚠️ 一部修正に失敗 ({applied_count}/{total} 成功)"
        else:
            status = f"✅ 全修正完了 ({applied_count} 件)"

        lines = [
            "## 🔧 自動修正PR完了",
            "",
            f"@{self.author} レビュー指摘に基づく修正PRを作成しました。内容を確認し、問題なければマージしてください。",
            "",
            f"**ステータス**: {status}",
            "",
            f"👉 **{fix_pr_url}**",
            "",
        ]

        if failed_count > 0:
            lines.append(f"- ✅ 成功: {applied_count} 件")
            lines.append(f"- ❌ 失敗: {failed_count} 件")
        if skipped_count > 0:
            lines.append(f"- ⏭️ スキップ: {skipped_count} 件")

        lines.extend([
            "",
            "各修正はレビューコメントで確認できます。",
            "",
            "---",
            "",
            "🤖 *Generated with [PR Reviewer](https://github.com/anthropics/claude-code)*",
        ])

        return "\n".join(lines)
