"""Configuration management for PR Reviewer."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    """Project-specific configuration."""

    unity_project_path: Path


class ReviewConfig(BaseModel):
    """Review behavior configuration."""

    enabled_reviewers: list[str] = Field(
        default_factory=lambda: [
            "runtime_error",
        ]
    )
    # 報告のみで修正を行わないレビュワー
    report_only_reviewers: list[str] = Field(default_factory=list)

    # コンパイルチェック設定
    compile_check_enabled: bool = True  # Phase3後にコンパイルチェックを実行
    compile_fix_max_attempts: int = 5  # コンパイルエラー修正の最大試行回数


class ClaudeConfig(BaseModel):
    """Claude CLI configuration."""

    model: str = "sonnet"  # Claude CLI uses short names like "sonnet", "opus"


class GitHubConfig(BaseModel):
    """GitHub configuration."""

    repo: str  # Repository in "owner/repo" format

    # Fix PR templates with placeholders:
    #   ($Branch) - target PR's branch name
    #   ($Timestamp) - timestamp (YYYYMMDD-HHMMSS)
    #   ($Number) - target PR's number
    #   ($Title) - target PR's title
    fix_branch_template: str = "fix/pr-($Number)-($Timestamp)"
    fix_pr_title_template: str = "[自動修正] #($Number)「($Title)」"


class Config(BaseModel):
    """Complete configuration."""

    project: ProjectConfig
    github: GitHubConfig
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    claude: ClaudeConfig = Field(default_factory=ClaudeConfig)

    @classmethod
    def load(cls) -> Config:
        """Load configuration from config.yaml."""
        data: dict = {}

        # Try to load from default locations
        default_paths = [
            Path("config.yaml"),
            Path(__file__).parent.parent / "config.yaml",
        ]
        for default_path in default_paths:
            if default_path.exists():
                with open(default_path) as f:
                    data = yaml.safe_load(f) or {}
                break

        # Validate required fields
        project_path = data.get("project", {}).get("unity_project_path")
        if not project_path:
            raise ValueError("project.unity_project_path is required in config.yaml")

        repo = data.get("github", {}).get("repo")
        if not repo:
            raise ValueError("github.repo is required in config.yaml")

        config = cls(
            project=ProjectConfig(
                unity_project_path=Path(project_path).expanduser()
            ),
            github=GitHubConfig(**data.get("github", {})),
            review=ReviewConfig(**data.get("review", {})),
            claude=ClaudeConfig(**data.get("claude", {})),
        )

        return config

    def validate_required(self) -> list[str]:
        """Validate that all required configuration is present."""
        errors = []
        if not self.project.unity_project_path.exists():
            errors.append(
                f"Unity project path does not exist: {self.project.unity_project_path}"
            )
        return errors
