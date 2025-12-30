"""GitHub API client using gh CLI."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PullRequest:
    """Pull request information."""

    number: int
    title: str
    body: str
    head_sha: str
    base_branch: str
    head_branch: str
    repository: str
    author: str
    url: str
    state: str = "OPEN"  # OPEN, MERGED, CLOSED


@dataclass
class ChangedFile:
    """Changed file in a pull request."""

    filename: str
    status: str  # added, modified, removed, renamed
    additions: int
    deletions: int
    patch: str | None = None


@dataclass
class DiffLine:
    """A line in a diff that can receive comments."""

    file_path: str
    line_number: int  # Line number in the new file
    side: str  # RIGHT for additions/context, LEFT for deletions
    content: str  # The actual line content (without +/- prefix)


class GitHubClient:
    """Client for interacting with GitHub via gh CLI."""

    def __init__(self, repository: str | None = None) -> None:
        """Initialize the GitHub client.

        Args:
            repository: Repository in owner/repo format. If None, uses current repo.
        """
        self.repository = repository
        self._resolved_repo: str | None = None

    def _get_repo(self) -> str:
        """Get the repository name, resolving from current directory if needed."""
        if self._resolved_repo:
            return self._resolved_repo

        if self.repository:
            self._resolved_repo = self.repository
        else:
            result = subprocess.run(
                ["gh", "repo", "view", "--json", "nameWithOwner"],
                capture_output=True,
                text=True,
                check=True,
            )
            self._resolved_repo = json.loads(result.stdout)["nameWithOwner"]

        return self._resolved_repo

    def _run_gh(
        self,
        args: list[str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a gh CLI command.

        Args:
            args: Arguments to pass to gh
            check: Whether to raise on non-zero exit

        Returns:
            Completed process result
        """
        cmd = ["gh"] + args
        # gh api doesn't support --repo flag, so skip it for api commands
        if self.repository and args and args[0] != "api":
            cmd.extend(["--repo", self.repository])

        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
        )

    def get_pull_request(self, pr_number: int) -> PullRequest:
        """Get pull request information.

        Args:
            pr_number: Pull request number

        Returns:
            PullRequest object
        """
        result = self._run_gh([
            "pr", "view", str(pr_number),
            "--json", "number,title,body,headRefOid,baseRefName,headRefName,url,author,state",
        ])

        data = json.loads(result.stdout)

        # Get repository from current directory if not set
        repo = self.repository
        if not repo:
            repo_result = self._run_gh(["repo", "view", "--json", "nameWithOwner"])
            repo = json.loads(repo_result.stdout)["nameWithOwner"]

        return PullRequest(
            number=data["number"],
            title=data["title"],
            body=data.get("body", ""),
            head_sha=data["headRefOid"],
            base_branch=data["baseRefName"],
            head_branch=data["headRefName"],
            repository=repo,
            author=data["author"]["login"],
            url=data["url"],
            state=data.get("state", "OPEN"),
        )

    def get_changed_files(self, pr_number: int) -> list[ChangedFile]:
        """Get list of changed files in a pull request.

        Args:
            pr_number: Pull request number

        Returns:
            List of ChangedFile objects
        """
        result = self._run_gh([
            "pr", "view", str(pr_number),
            "--json", "files",
        ])

        data = json.loads(result.stdout)
        files = []

        for f in data.get("files", []):
            files.append(ChangedFile(
                filename=f["path"],
                status=self._map_status(f.get("status", "modified")),
                additions=f.get("additions", 0),
                deletions=f.get("deletions", 0),
            ))

        return files

    def _map_status(self, status: str) -> str:
        """Map GitHub file status to our status.

        Args:
            status: GitHub status string

        Returns:
            Normalized status
        """
        status_map = {
            "A": "added",
            "M": "modified",
            "D": "removed",
            "R": "renamed",
            "added": "added",
            "modified": "modified",
            "removed": "removed",
            "renamed": "renamed",
        }
        return status_map.get(status, "modified")

    def create_review_comment(
        self,
        pr_number: int,
        body: str,
        commit_sha: str,
        path: str,
        line: int,
        start_line: int | None = None,
        side: str = "RIGHT",
    ) -> dict[str, Any]:
        """Create a review comment on a specific line or line range.

        Args:
            pr_number: Pull request number
            body: Comment body (markdown)
            commit_sha: Commit SHA to comment on
            path: File path
            line: Line number (end line for multi-line)
            start_line: Start line for multi-line comments (optional)
            side: Side of the diff (LEFT or RIGHT)

        Returns:
            Created comment data
        """
        # Build payload as JSON (avoids shell escaping issues)
        repo = self._get_repo()
        payload: dict[str, Any] = {
            "body": body,
            "commit_id": commit_sha,
            "path": path,
            "line": line,
            "side": side,
        }

        # Add start_line for multi-line comments
        if start_line is not None and start_line != line:
            payload["start_line"] = start_line
            payload["start_side"] = side

        # Use stdin to pass JSON payload (avoids escaping issues)
        cmd = [
            "gh", "api",
            f"repos/{repo}/pulls/{pr_number}/comments",
            "-X", "POST",
            "--input", "-",
        ]

        result = subprocess.run(
            cmd,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=True,
        )

        return json.loads(result.stdout)

    def create_issue_comment(
        self,
        pr_number: int,
        body: str,
    ) -> dict[str, Any]:
        """Create a general comment on the PR.

        Args:
            pr_number: Pull request number
            body: Comment body (markdown)

        Returns:
            Created comment data
        """
        result = self._run_gh([
            "pr", "comment", str(pr_number),
            "--body", body,
        ])

        return {"status": "created", "output": result.stdout}

    def create_review(
        self,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
        comments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a pull request review.

        Args:
            pr_number: Pull request number
            body: Review body
            event: Review event (APPROVE, REQUEST_CHANGES, COMMENT)
            comments: List of review comments

        Returns:
            Created review data
        """
        # Build the review payload
        payload = {
            "body": body,
            "event": event,
        }

        if comments:
            payload["comments"] = comments

        # Use gh api to create a review
        repo = self._get_repo()
        result = self._run_gh([
            "api",
            f"repos/{repo}/pulls/{pr_number}/reviews",
            "-X", "POST",
            "--input", "-",
        ], check=False)

        # Pass payload via stdin would require different approach
        # For now, create review without inline comments
        args = ["pr", "review", str(pr_number)]

        if event == "APPROVE":
            args.append("--approve")
        elif event == "REQUEST_CHANGES":
            args.append("--request-changes")
        else:
            args.append("--comment")

        if body:
            args.extend(["--body", body])

        result = self._run_gh(args)

        return {"status": "created", "output": result.stdout}

    def get_pr_diff(self, pr_number: int) -> str:
        """Get the diff for a pull request.

        Args:
            pr_number: Pull request number

        Returns:
            Diff as string
        """
        result = self._run_gh([
            "pr", "diff", str(pr_number),
        ])
        return result.stdout

    def parse_diff_lines(self, diff: str) -> dict[str, dict[int, DiffLine]]:
        """Parse a diff and extract commentable lines.

        Args:
            diff: Diff string from get_pr_diff

        Returns:
            Dict mapping file_path -> {line_number -> DiffLine}
        """
        import re

        result: dict[str, dict[int, DiffLine]] = {}
        current_file: str | None = None
        new_line_num = 0

        for line in diff.split("\n"):
            # Match file header: diff --git a/path b/path
            file_match = re.match(r"^diff --git a/.+ b/(.+)$", line)
            if file_match:
                current_file = file_match.group(1)
                result[current_file] = {}
                continue

            # Match hunk header: @@ -old_start,old_count +new_start,new_count @@
            hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if hunk_match:
                new_line_num = int(hunk_match.group(1))
                continue

            if current_file is None:
                continue

            # Process diff lines
            if line.startswith("+") and not line.startswith("+++"):
                # Added line - commentable on RIGHT side
                result[current_file][new_line_num] = DiffLine(
                    file_path=current_file,
                    line_number=new_line_num,
                    side="RIGHT",
                    content=line[1:],  # Remove + prefix
                )
                new_line_num += 1
            elif line.startswith("-") and not line.startswith("---"):
                # Deleted line - don't increment new line number
                # Could comment on LEFT side but we focus on RIGHT
                pass
            elif line.startswith(" "):
                # Context line - commentable on RIGHT side
                result[current_file][new_line_num] = DiffLine(
                    file_path=current_file,
                    line_number=new_line_num,
                    side="RIGHT",
                    content=line[1:],  # Remove space prefix
                )
                new_line_num += 1
            # Skip other lines (headers, etc.)

        return result

    def get_commentable_lines(self, pr_number: int) -> dict[str, set[int]]:
        """Get all line numbers that can receive comments for each file.

        Args:
            pr_number: Pull request number

        Returns:
            Dict mapping file_path -> set of commentable line numbers
        """
        diff = self.get_pr_diff(pr_number)
        diff_lines = self.parse_diff_lines(diff)

        return {
            file_path: set(lines.keys())
            for file_path, lines in diff_lines.items()
        }

    def get_file_content(
        self,
        path: str,
        ref: str | None = None,
    ) -> str:
        """Get file content from repository.

        Args:
            path: File path
            ref: Git ref (branch, tag, commit). If None, uses default branch.

        Returns:
            File content as string
        """
        repo = self._get_repo()
        args = ["api", f"repos/{repo}/contents/{path}"]

        if ref:
            args.extend(["-f", f"ref={ref}"])

        result = self._run_gh(args)
        data = json.loads(result.stdout)

        if data.get("encoding") == "base64":
            import base64
            return base64.b64decode(data["content"]).decode("utf-8")

        return data.get("content", "")

    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool = False,
    ) -> dict[str, Any]:
        """Create a new pull request.

        Args:
            title: PR title
            body: PR body/description (markdown)
            head: Head branch name (source branch with changes)
            base: Base branch name (target branch to merge into)
            draft: Whether to create as draft PR

        Returns:
            Dict with PR info including 'number' and 'url'
        """
        cmd = [
            "pr", "create",
            "--title", title,
            "--body", body,
            "--head", head,
            "--base", base,
        ]

        if draft:
            cmd.append("--draft")

        result = self._run_gh(cmd)

        # Parse the URL from output (gh pr create outputs the PR URL)
        url = result.stdout.strip()

        # Extract PR number from URL
        pr_number = int(url.rstrip("/").split("/")[-1])

        return {
            "number": pr_number,
            "url": url,
        }

    def update_pull_request(
        self,
        pr_number: int,
        title: str | None = None,
        body: str | None = None,
    ) -> bool:
        """Update a pull request.

        Args:
            pr_number: PR number to update
            title: New title (optional)
            body: New body (optional)

        Returns:
            True if update was successful
        """
        cmd = ["pr", "edit", str(pr_number)]

        if title:
            cmd.extend(["--title", title])
        if body:
            cmd.extend(["--body", body])

        if len(cmd) == 3:
            # No changes specified
            return True

        try:
            self._run_gh(cmd)
            return True
        except Exception:
            return False

    def mark_pr_ready(self, pr_number: int) -> bool:
        """Mark a draft PR as ready for review.

        Args:
            pr_number: PR number to mark as ready

        Returns:
            True if successful
        """
        try:
            self._run_gh(["pr", "ready", str(pr_number)])
            return True
        except Exception:
            return False
