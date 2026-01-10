"""Git operations wrapper for repository management."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitOperations:
    """Helper for git operations on a repository."""

    def __init__(self, repo_path: Path) -> None:
        """Initialize with repository path.

        Args:
            repo_path: Path to the git repository
        """
        self.repo_path = repo_path

    def _run(
        self,
        args: list[str],
        check: bool = True,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess:
        """Run a git command.

        Args:
            args: Git command arguments (without 'git' prefix)
            check: Whether to raise on non-zero exit
            capture_output: Whether to capture stdout/stderr

        Returns:
            CompletedProcess result
        """
        cmd = ["git"] + args
        return subprocess.run(
            cmd,
            cwd=self.repo_path,
            check=check,
            capture_output=capture_output,
            text=True,
        )

    def fetch_remote_branch(self, branch: str, remote: str = "origin") -> bool:
        """Fetch a specific branch from remote.

        Args:
            branch: Branch name to fetch
            remote: Remote name (default: origin)

        Returns:
            True if successful
        """
        try:
            self._run(["fetch", remote, branch])
            return True
        except subprocess.CalledProcessError:
            return False

    def checkout_branch(self, branch: str, create: bool = False) -> bool:
        """Checkout or create a branch.

        Args:
            branch: Branch name
            create: Whether to create the branch if it doesn't exist

        Returns:
            True if successful
        """
        try:
            if create:
                self._run(["checkout", "-b", branch])
            else:
                self._run(["checkout", branch])
            return True
        except subprocess.CalledProcessError:
            return False

    def create_branch_from(
        self,
        new_branch: str,
        base_ref: str,
        remote: str = "origin",
    ) -> bool:
        """Create a new branch from a specific ref.

        Args:
            new_branch: Name for the new branch
            base_ref: Base reference (branch name or commit)
            remote: Remote name for the base ref

        Returns:
            True if successful
        """
        try:
            # First try to checkout the remote branch
            self._run(["checkout", "-b", new_branch, f"{remote}/{base_ref}"])
            return True
        except subprocess.CalledProcessError:
            return False

    def create_branch_from_sha(self, new_branch: str, commit_sha: str) -> bool:
        """Create a new branch from a specific commit SHA.

        Args:
            new_branch: Name for the new branch
            commit_sha: Commit SHA to base the branch on

        Returns:
            True if successful
        """
        try:
            self._run(["checkout", "-b", new_branch, commit_sha])
            return True
        except subprocess.CalledProcessError:
            return False

    def fetch_commit(self, commit_sha: str, remote: str = "origin") -> bool:
        """Fetch a specific commit from remote.

        Args:
            commit_sha: Commit SHA to fetch
            remote: Remote name

        Returns:
            True if successful
        """
        try:
            self._run(["fetch", remote, commit_sha])
            return True
        except subprocess.CalledProcessError:
            return False

    def stage_files(self, files: list[str]) -> bool:
        """Stage specific files for commit.

        Args:
            files: List of file paths to stage

        Returns:
            True if successful
        """
        try:
            self._run(["add"] + files)
            return True
        except subprocess.CalledProcessError:
            return False

    def stage_all(self) -> bool:
        """Stage all modified files.

        Returns:
            True if successful
        """
        try:
            self._run(["add", "-A"])
            return True
        except subprocess.CalledProcessError:
            return False

    def commit(self, message: str) -> bool:
        """Create a commit with the staged changes.

        Args:
            message: Commit message

        Returns:
            True if successful
        """
        try:
            self._run(["commit", "-m", message])
            return True
        except subprocess.CalledProcessError:
            return False

    def push(self, branch: str, set_upstream: bool = True, remote: str = "origin") -> bool:
        """Push branch to remote.

        Args:
            branch: Branch name to push
            set_upstream: Whether to set upstream tracking
            remote: Remote name

        Returns:
            True if successful
        """
        try:
            args = ["push"]
            if set_upstream:
                args.extend(["-u", remote, branch])
            else:
                args.extend([remote, branch])
            self._run(args)
            return True
        except subprocess.CalledProcessError:
            return False

    def get_current_branch(self) -> str | None:
        """Get current branch name.

        Returns:
            Current branch name or None if not on a branch
        """
        try:
            result = self._run(["rev-parse", "--abbrev-ref", "HEAD"])
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None

    def has_uncommitted_changes(self) -> bool:
        """Check if there are uncommitted changes.

        Returns:
            True if there are uncommitted changes
        """
        try:
            result = self._run(["status", "--porcelain"])
            return bool(result.stdout.strip())
        except subprocess.CalledProcessError:
            return False

    def stash_push(self, message: str | None = None) -> bool:
        """Stash current changes.

        Args:
            message: Optional stash message

        Returns:
            True if successful
        """
        try:
            args = ["stash", "push"]
            if message:
                args.extend(["-m", message])
            self._run(args)
            return True
        except subprocess.CalledProcessError:
            return False

    def stash_pop(self) -> bool:
        """Pop stashed changes.

        Returns:
            True if successful
        """
        try:
            self._run(["stash", "pop"])
            return True
        except subprocess.CalledProcessError:
            return False

    def reset_hard(self, ref: str = "HEAD") -> bool:
        """Hard reset to a specific ref.

        Args:
            ref: Reference to reset to

        Returns:
            True if successful
        """
        try:
            self._run(["reset", "--hard", ref])
            return True
        except subprocess.CalledProcessError:
            return False

    def delete_branch(self, branch: str, force: bool = False) -> bool:
        """Delete a local branch.

        Args:
            branch: Branch name to delete
            force: Force delete even if not merged

        Returns:
            True if successful
        """
        try:
            flag = "-D" if force else "-d"
            self._run(["branch", flag, branch])
            return True
        except subprocess.CalledProcessError:
            return False

    def branch_exists(self, branch: str, remote: str | None = None) -> bool:
        """Check if a branch exists.

        Args:
            branch: Branch name to check
            remote: Remote name to check remote branches

        Returns:
            True if branch exists
        """
        try:
            if remote:
                ref = f"refs/remotes/{remote}/{branch}"
            else:
                ref = f"refs/heads/{branch}"
            self._run(["show-ref", "--verify", "--quiet", ref])
            return True
        except subprocess.CalledProcessError:
            return False

    def get_diff_against_branch(self, base_branch: str) -> str | None:
        """Get diff between current HEAD and a base branch.

        Uses the three-dot diff (base...HEAD) to get changes
        since the branches diverged.

        Args:
            base_branch: Base branch to compare against

        Returns:
            Diff content as string, or None on error
        """
        try:
            result = self._run(["diff", f"{base_branch}...HEAD"])
            return result.stdout
        except subprocess.CalledProcessError:
            return None

    def get_changed_files_against_branch(
        self, base_branch: str
    ) -> list[dict[str, str]] | None:
        """Get list of changed files between current HEAD and a base branch.

        Args:
            base_branch: Base branch to compare against

        Returns:
            List of dicts with 'filename', 'status', 'additions', 'deletions', or None on error
        """
        try:
            # Get file stats (additions/deletions) with --numstat
            numstat_result = self._run(["diff", "--numstat", f"{base_branch}...HEAD"])
            file_stats = {}
            for line in numstat_result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 3:
                    additions = int(parts[0]) if parts[0] != "-" else 0
                    deletions = int(parts[1]) if parts[1] != "-" else 0
                    filename = parts[2]
                    file_stats[filename] = {"additions": additions, "deletions": deletions}

            # Get file status (modified/added/deleted) with --name-status
            status_result = self._run(["diff", "--name-status", f"{base_branch}...HEAD"])
            files = []
            for line in status_result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    status_code = parts[0][0]  # First char (M, A, D, R, etc.)
                    filename = parts[-1]  # Last part is the filename

                    # Map git status codes to human-readable status
                    status_map = {
                        "M": "modified",
                        "A": "added",
                        "D": "deleted",
                        "R": "renamed",
                        "C": "copied",
                    }
                    status = status_map.get(status_code, "modified")

                    stats = file_stats.get(filename, {"additions": 0, "deletions": 0})
                    files.append({
                        "filename": filename,
                        "status": status,
                        "additions": stats["additions"],
                        "deletions": stats["deletions"],
                    })
            return files
        except subprocess.CalledProcessError:
            return None

    def get_merge_base(self, base_branch: str) -> str | None:
        """Get the merge base between current HEAD and a base branch.

        Args:
            base_branch: Base branch to compare against

        Returns:
            Merge base commit SHA, or None on error
        """
        try:
            result = self._run(["merge-base", base_branch, "HEAD"])
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None

    def get_head_commit(self) -> str | None:
        """Get the current HEAD commit SHA.

        Returns:
            40-character commit SHA, or None on error
        """
        try:
            result = self._run(["rev-parse", "HEAD"])
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None

    def get_commit_diff(self, commit_hash: str) -> str | None:
        """Get the diff for a specific commit.

        Args:
            commit_hash: Commit hash to get diff for

        Returns:
            Diff string, or None on error
        """
        try:
            result = self._run(["show", "--format=", commit_hash])
            return result.stdout
        except subprocess.CalledProcessError:
            return None

    def find_largest_hunk(self, diff: str) -> tuple[str, int, int] | None:
        """Find the largest hunk in a diff.

        Hunk size is determined by the total number of changed lines (+ and -).

        Args:
            diff: Git diff format string

        Returns:
            (file_path, start_line, end_line) or None if not found.
            end_line is capped at start_line + 9 (max 10 lines).
        """
        import re

        largest_hunk: tuple[str, int, int, int] | None = None  # (file, start, end, size)
        current_file: str | None = None

        lines = diff.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]

            # Match file header: diff --git a/path b/path
            file_match = re.match(r"^diff --git a/.+ b/(.+)$", line)
            if file_match:
                current_file = file_match.group(1)
                i += 1
                continue

            # Match hunk header: @@ -old_start,count +new_start,count @@
            hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if hunk_match and current_file:
                hunk_start = int(hunk_match.group(1))
                i += 1

                # Count changed lines in this hunk
                change_count = 0
                hunk_lines = 0
                while i < len(lines):
                    hunk_line = lines[i]
                    if hunk_line.startswith("diff --git") or hunk_line.startswith("@@"):
                        break
                    if hunk_line.startswith("+") and not hunk_line.startswith("+++"):
                        change_count += 1
                        hunk_lines += 1
                    elif hunk_line.startswith("-") and not hunk_line.startswith("---"):
                        change_count += 1
                    elif hunk_line.startswith(" "):
                        hunk_lines += 1
                    i += 1

                if change_count > 0:
                    # Cap end_line at start + 9 (max 10 lines)
                    end_line = hunk_start + min(hunk_lines - 1, 9) if hunk_lines > 0 else hunk_start

                    if largest_hunk is None or change_count > largest_hunk[3]:
                        largest_hunk = (current_file, hunk_start, end_line, change_count)
                continue

            i += 1

        if largest_hunk:
            return (largest_hunk[0], largest_hunk[1], largest_hunk[2])
        return None
