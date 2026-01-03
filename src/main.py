"""Main entry point for PR Reviewer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config import Config
from src.github import GitHubClient
from src.github.git_operations import GitOperations
from src.models import PRInfo
from src.orchestrator import ReviewOrchestrator

console = Console()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Claude CLI を使った自動PRレビュー"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Review command
    review_parser = subparsers.add_parser("review", help="Review a PR and create fix PR")
    review_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="Pull request number",
    )
    review_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output",
    )
    review_parser.add_argument(
        "--no-pr",
        action="store_true",
        help="Don't create fix PR (default: create fix PR)",
    )

    # Local review command (review current branch against base)
    local_parser = subparsers.add_parser(
        "local", help="Review current branch against a base branch"
    )
    local_parser.add_argument(
        "--base",
        type=str,
        required=True,
        help="Base branch to compare against (e.g., main)",
    )
    local_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output",
    )
    local_parser.add_argument(
        "--no-fix",
        action="store_true",
        help="Skip fix application (analysis only)",
    )

    # Status command
    subparsers.add_parser("status", help="Show current review status")

    # Fix PR command (create a PR with all verified suggestions applied)
    fix_pr_parser = subparsers.add_parser(
        "fix-pr", help="Create a fix PR with all verified suggestions applied"
    )
    fix_pr_parser.add_argument(
        "--review-dir",
        type=Path,
        required=True,
        help="Path to review directory (e.g., reviews/36-20251231-123456)",
    )
    fix_pr_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="Original pull request number",
    )
    fix_pr_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    fix_pr_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output",
    )

    return parser.parse_args()


def run_github_review(
    pr_number: int,
    debug: bool = False,
    create_fix_pr: bool = True,
) -> int:
    """Run a review on a GitHub PR and create fix PR.

    Args:
        pr_number: Pull request number
        debug: Whether to enable debug output
        create_fix_pr: If True, create a fix PR with all verified suggestions.

    Returns:
        Exit code
    """
    config = Config.load()

    # Validate config
    errors = config.validate_required()
    if errors:
        for error in errors:
            console.print(f"[red]Error: {error}[/red]")
        return 1

    # Initialize GitHub client
    gh_client = GitHubClient(repository=config.github.repo)

    # Initialize git operations (will be set up later)
    git: GitOperations | None = None
    original_branch: str | None = None

    try:
        # Get PR info
        console.print(f"[cyan]PR #{pr_number} の情報を取得中...[/cyan]")
        pr = gh_client.get_pull_request(pr_number)

        console.print(f"[green]PR: {pr.title}[/green]")
        console.print(f"[dim]Author: {pr.author} | Branch: {pr.head_branch} → {pr.base_branch}[/dim]")

        # Get changed files
        changed_files = gh_client.get_changed_files(pr_number)
        console.print(f"[cyan]{len(changed_files)} 個のファイルが変更されています[/cyan]")

        # Get PR diff
        pr_diff = gh_client.get_pr_diff(pr_number)

        # Create PR info for orchestrator
        pr_info = PRInfo(
            repository=pr.repository,
            number=pr.number,
            base_branch=pr.base_branch,
            head_branch=pr.head_branch,
            url=pr.url,
        )

        # Create changed files list for orchestrator
        changed_files_list = [
            {
                "filename": f.filename,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions,
            }
            for f in changed_files
        ]

        # Setup fix branch for commits
        project_path = Path(config.project.unity_project_path).expanduser()
        git = GitOperations(project_path)

        # Determine base branch for fix branch
        is_merged = pr.state == "MERGED"

        # Create fix branch name with timestamp using template
        from datetime import datetime
        from src.github.fix_pr_creator import expand_template
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        fix_branch = expand_template(
            config.github.fix_branch_template,
            branch=pr.head_branch,
            timestamp=timestamp,
            number=pr_number,
            title=pr.title,
        )

        # Save original branch for cleanup
        original_branch = git.get_current_branch()

        # Fetch PR's head commit for review
        console.print(f"[cyan]PR のコード (HEAD: {pr.head_sha[:8]}) を取得中...[/cyan]")
        git.fetch_commit(pr.head_sha)

        # Create fix branch from PR's head commit for review
        console.print(f"[cyan]Fix用ブランチを作成中: {fix_branch}[/cyan]")
        if not git.create_branch_from_sha(fix_branch, pr.head_sha):
            console.print(f"[red]ブランチの作成に失敗しました[/red]")
            return 1

        if debug:
            print(f"[DEBUG] Created fix branch: {fix_branch} from {pr.head_sha[:8]}")

        # Parse repository owner and name from URL
        # URL format: https://github.com/owner/repo
        import re
        repo_match = re.search(r'github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$', pr.url.replace('/pull/', '/'))
        if repo_match:
            repo_owner = repo_match.group(1)
            repo_name = repo_match.group(2)
        else:
            # Fallback: extract from repository field
            parts = pr.repository.split('/')
            repo_owner = parts[0] if len(parts) >= 2 else ""
            repo_name = parts[1] if len(parts) >= 2 else pr.repository

        # Run review
        reviews_dir = Path(__file__).parent.parent / "reviews"
        orchestrator = ReviewOrchestrator(config, reviews_dir, debug=debug)

        # Set environment variables for Claude's Bash commands
        target_branch = pr.base_branch if is_merged else pr.head_branch
        orchestrator.set_env_vars(
            fix_branch=fix_branch,
            target_branch=target_branch,
            repo_owner=repo_owner,
            repo_name=repo_name,
            original_pr_number=pr_number,
        )

        try:
            # Phase 1: Parallel analysis (no edits, no commits)
            orchestrator.start_review(pr_info, changed_files_list, pr_diff=pr_diff)
            orchestrator.run_review_phase()
        except Exception as e:
            # Cleanup: restore original branch on failure
            console.print(f"[red]レビュー中にエラー: {e}[/red]")
            git.checkout_branch(original_branch)
            git.delete_branch(fix_branch, force=True)
            raise

        # Print Phase 1 summary
        summary = orchestrator.get_review_summary()
        print_summary(summary)

        # Phase 2 & 3: Create fix PR and apply fixes
        if create_fix_pr and orchestrator.metadata and orchestrator.metadata.findings:
            from src.github.fix_pr_creator import FixPRCreator

            findings_count = len(orchestrator.metadata.findings)
            console.print()
            console.print(f"[cyan]Phase 2: Draft Fix PR を作成中... ({findings_count} 件の問題)[/cyan]")

            # Assign sequential numbers to findings
            orchestrator.assign_finding_numbers()

            creator = FixPRCreator(
                github_client=gh_client,
                project_path=Path(config.project.unity_project_path),
                debug=debug,
                pr_title_template=config.github.fix_pr_title_template,
            )

            # Create draft PR with summary table
            fix_result = creator.create_fix_pr(
                original_pr_number=pr_number,
                metadata=orchestrator.metadata,
                as_draft=True,
            )

            if fix_result.success:
                console.print("[green]✓ Draft Fix PR を作成しました[/green]")
                console.print(f"  [bold]URL: {fix_result.fix_pr_url}[/bold]")

                # Update environment with fix PR number
                orchestrator.set_env_vars(
                    fix_branch=fix_branch,
                    target_branch=target_branch,
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    original_pr_number=pr_number,
                    fix_pr_number=fix_result.fix_pr_number,
                )

                # Phase 3: Apply fixes sequentially
                console.print()
                console.print("[cyan]Phase 3: 修正を順次適用中...[/cyan]")

                def on_finding_fixed(finding, success):
                    """Callback after each fix is applied."""
                    if not fix_result.fix_pr_number:
                        return

                    # Always post comment and save URL
                    # The comment will be posted to explain the finding and provide context
                    comment_url = creator.post_single_explanation_comment(
                        fix_result.fix_pr_number,
                        finding,
                    )
                    if comment_url:
                        finding.comment_url = comment_url
                    elif debug:
                        console.print(f"[yellow]⚠ コメント投稿に失敗: ({finding.number})[/yellow]")

                    # Always update PR body with new status (now includes comment_url)
                    creator.update_pr_body(
                        fix_result.fix_pr_number,
                        pr_number,
                        orchestrator.metadata,
                    )

                fix_results = orchestrator.run_fix_application_phase(
                    on_finding_fixed=on_finding_fixed
                )

                console.print()
                console.print(f"[green]✓ 修正適用完了[/green]")
                console.print(f"  成功: {len(fix_results['applied'])} 件")
                if fix_results['failed']:
                    console.print(f"  [red]失敗: {len(fix_results['failed'])} 件[/red]")
                if fix_results['skipped']:
                    console.print(f"  [dim]スキップ: {len(fix_results['skipped'])} 件[/dim]")

                # Mark draft PR as ready for review
                if fix_results['applied']:
                    console.print()
                    console.print("[cyan]Draft PRをOpenに変更中...[/cyan]")
                    if creator.mark_pr_ready(fix_result.fix_pr_number):
                        console.print("[green]✓ PRをレビュー可能な状態にしました[/green]")
                    else:
                        console.print("[yellow]⚠ PRのDraft解除に失敗しました（手動で解除してください）[/yellow]")
            else:
                console.print("[red]✗ Draft Fix PR の作成に失敗しました[/red]")
                for error in fix_result.errors:
                    console.print(f"  [red]{error}[/red]")
        elif create_fix_pr:
            console.print()
            console.print("[yellow]問題が見つからなかったため、Fix PR は作成しませんでした[/yellow]")

        # Restore original branch after successful operation
        if git and original_branch:
            git.checkout_branch(original_branch)

        return 0

    except Exception as e:
        console.print(f"[red]レビュー中にエラーが発生しました: {e}[/red]")
        # Cleanup: restore original branch
        if git and original_branch:
            try:
                git.checkout_branch(original_branch)
            except Exception:
                pass
        if debug:
            import traceback
            traceback.print_exc()
        return 1


def run_local_branch_review(
    base_branch: str,
    debug: bool = False,
    apply_fixes: bool = True,
) -> int:
    """Run a local review comparing current branch against a base branch.

    Args:
        base_branch: Base branch to compare against (e.g., main)
        debug: Whether to enable debug output
        apply_fixes: Whether to apply fixes (Phase 3)

    Returns:
        Exit code
    """
    config = Config.load()

    # Validate config
    errors = config.validate_required()
    if errors:
        for error in errors:
            console.print(f"[red]Error: {error}[/red]")
        return 1

    project_path = Path(config.project.unity_project_path).expanduser()
    git = GitOperations(project_path)

    # Get current branch
    current_branch = git.get_current_branch()
    if not current_branch:
        console.print("[red]Error: 現在のブランチを取得できませんでした[/red]")
        return 1

    console.print(f"[cyan]現在のブランチ: {current_branch}[/cyan]")
    console.print(f"[cyan]比較対象: {base_branch}[/cyan]")

    # Get diff and changed files
    console.print(f"[cyan]差分を取得中...[/cyan]")
    pr_diff = git.get_diff_against_branch(base_branch)
    if pr_diff is None:
        console.print(f"[red]Error: {base_branch} との差分を取得できませんでした[/red]")
        return 1

    changed_files = git.get_changed_files_against_branch(base_branch)
    if changed_files is None:
        console.print(f"[red]Error: 変更ファイル一覧を取得できませんでした[/red]")
        return 1

    if not changed_files:
        console.print(f"[yellow]{base_branch} との間に変更がありません[/yellow]")
        return 0

    console.print(f"[green]{len(changed_files)} 個のファイルが変更されています[/green]")

    # Create PR info for orchestrator (local mode)
    pr_info = PRInfo(
        repository="local/branch",
        number=0,
        base_branch=base_branch,
        head_branch=current_branch,
        url=f"local://{current_branch}",
    )

    # Run review
    reviews_dir = Path(__file__).parent.parent / "reviews"
    orchestrator = ReviewOrchestrator(config, reviews_dir, debug=debug)

    try:
        # Phase 1: Parallel analysis
        orchestrator.start_review(pr_info, changed_files, pr_diff=pr_diff)
        orchestrator.run_review_phase()

        # Print Phase 1 summary
        summary = orchestrator.get_review_summary()
        print_summary(summary)

        # Phase 3: Apply fixes locally (no PR)
        if apply_fixes and orchestrator.metadata and orchestrator.metadata.findings:
            findings_count = len(orchestrator.metadata.findings)
            console.print()
            console.print(f"[cyan]Phase 3: 修正を適用中... ({findings_count} 件の問題)[/cyan]")

            # Assign sequential numbers to findings
            orchestrator.assign_finding_numbers()

            fix_results = orchestrator.run_local_fix_application_phase()

            console.print()
            console.print(f"[green]✓ 修正適用完了[/green]")
            console.print(f"  成功: {len(fix_results['applied'])} 件")
            if fix_results['failed']:
                console.print(f"  [red]失敗: {len(fix_results['failed'])} 件[/red]")
            if fix_results['skipped']:
                console.print(f"  [dim]スキップ: {len(fix_results['skipped'])} 件[/dim]")

        # Generate markdown report
        if orchestrator.metadata and orchestrator.review_path:
            report_path = orchestrator.generate_markdown_report()
            console.print()
            console.print(f"[green]✓ レポートを生成しました: {report_path}[/green]")

        return 0

    except Exception as e:
        console.print(f"[red]レビュー中にエラーが発生しました: {e}[/red]")
        if debug:
            import traceback
            traceback.print_exc()
        return 1


def run_fix_pr(
    review_dir: Path,
    pr_number: int,
    dry_run: bool = False,
    debug: bool = False,
) -> int:
    """Create a fix PR with all verified suggestions applied.

    Args:
        review_dir: Path to review directory
        pr_number: Original pull request number
        dry_run: Show what would be done without making changes
        debug: Whether to enable debug output

    Returns:
        Exit code
    """
    import json

    from src.github.fix_pr_creator import FixPRCreator
    from src.models import Metadata

    config = Config.load()

    # Validate config
    errors = config.validate_required()
    if errors:
        for error in errors:
            console.print(f"[red]Error: {error}[/red]")
        return 1

    # Load metadata from review directory
    metadata_file = review_dir / "metadata.json"
    if not metadata_file.exists():
        console.print(f"[red]メタデータが見つかりません: {metadata_file}[/red]")
        return 1

    try:
        with open(metadata_file) as f:
            data = json.load(f)
        metadata = Metadata.model_validate(data)

        # Count findings with commits (verified fixes)
        findings_with_commits = [f for f in metadata.findings if f.commit_hash]
        commit_count = len(findings_with_commits)

        console.print(Panel("Fix PR 作成", style="bold green"))
        console.print(f"[dim]レビューディレクトリ: {review_dir}[/dim]")
        console.print(f"[dim]元PR: #{pr_number}[/dim]")
        console.print(f"[dim]プロジェクト: {config.project.unity_project_path}[/dim]")
        console.print()
        console.print(f"[cyan]検出した問題: {len(metadata.findings)} 件[/cyan]")
        console.print(f"[cyan]修正コミット: {commit_count} 件[/cyan]")
        console.print()

        if commit_count == 0:
            console.print("[yellow]修正コミットがありません[/yellow]")
            return 1

        if dry_run:
            console.print("[yellow]Dry run モード: 実際の変更は行いません[/yellow]")
            console.print()
            console.print("[bold]適用予定の修正:[/bold]")
            for finding in findings_with_commits:
                console.print(f"  - [{finding.id}] {finding.title} ({finding.file}) - commit: {finding.commit_hash}")
            return 0

        # Initialize GitHub client and fix PR creator
        gh_client = GitHubClient(repository=config.github.repo)
        creator = FixPRCreator(
            github_client=gh_client,
            project_path=Path(config.project.unity_project_path),
            debug=debug,
            pr_title_template=config.github.fix_pr_title_template,
        )

        console.print("[cyan]Fix PR を作成中...[/cyan]")
        result = creator.create_fix_pr(
            original_pr_number=pr_number,
            metadata=metadata,
        )

        console.print()

        if result.success:
            console.print("[green]✓ Fix PR を作成しました[/green]")
            console.print(f"  [bold]URL: {result.fix_pr_url}[/bold]")
            console.print(f"  ブランチ: {result.branch_name}")
            console.print(f"  適用した修正: {len(result.applied_findings)} 件")
            if result.failed_findings:
                console.print(f"  [yellow]適用失敗: {len(result.failed_findings)} 件[/yellow]")
            return 0
        else:
            console.print("[red]✗ Fix PR の作成に失敗しました[/red]")
            for error in result.errors:
                console.print(f"  [red]{error}[/red]")
            if result.applied_findings:
                console.print(f"  適用済み: {len(result.applied_findings)} 件")
            if result.failed_findings:
                console.print(f"  適用失敗: {len(result.failed_findings)} 件")
            return 1

    except Exception as e:
        console.print(f"[red]エラーが発生しました: {e}[/red]")
        if debug:
            import traceback
            traceback.print_exc()
        return 1


def print_summary(summary: dict) -> None:
    """Print a review summary.

    Args:
        summary: Summary dictionary
    """
    console.print()
    console.print(Panel("レビュー結果サマリー", style="bold blue"))

    table = Table(show_header=False)
    table.add_column("項目", style="cyan")
    table.add_column("値", style="white")

    table.add_row("リポジトリ", summary["pr"]["repository"])
    table.add_row("PR番号", str(summary["pr"]["number"]))
    table.add_row("ステータス", summary["status"])
    table.add_row("現在のフェーズ", summary["current_phase"])
    table.add_row("変更ファイル数", str(summary["changed_files"]))
    table.add_row("検出した問題数", str(summary["findings"]["total"]))

    console.print(table)


def main() -> int:
    """Main entry point."""
    args = parse_args()

    if args.command == "local":
        return run_local_branch_review(
            base_branch=args.base,
            debug=args.debug,
            apply_fixes=not args.no_fix,
        )
    elif args.command == "review":
        return run_github_review(
            pr_number=args.pr,
            debug=args.debug,
            create_fix_pr=not args.no_pr,
        )
    elif args.command == "fix-pr":
        return run_fix_pr(
            review_dir=args.review_dir,
            pr_number=args.pr,
            dry_run=args.dry_run,
            debug=args.debug,
        )
    elif args.command == "status":
        console.print("[yellow]status コマンドは未実装です[/yellow]")
        return 1
    else:
        console.print("使用方法は --help を参照してください")
        return 1


if __name__ == "__main__":
    sys.exit(main())
