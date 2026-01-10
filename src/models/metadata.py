"""Metadata models for PR review state management."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

# 動的にReviewerType Enumを生成
# NOTE: 循環インポートを避けるため、reviewer_registryは他のモデルに依存しない
from src.reviewer_registry import get_reviewer_type

ReviewerType = get_reviewer_type()

if TYPE_CHECKING:
    # 型チェック時のみ使用（実行時は上で定義したReviewerTypeを使用）
    pass


class Phase(str, Enum):
    """Review phases."""

    INITIALIZATION = "initialization"
    EXPLORATION = "exploration"
    DEEP_ANALYSIS = "deep_analysis"  # Phase 1: Parallel review (analysis only)
    FIX_PR_CREATION = "fix_pr_creation"  # Phase 2: Create draft PR with summary
    FIX_APPLICATION = "fix_application"  # Phase 3: Sequential fix application
    COMMENT_POSTING = "comment_posting"


class Status(str, Enum):
    """Status values."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class ChangedFile(BaseModel):
    """Information about a changed file in the PR."""

    path: str
    status: str  # "added", "modified", "deleted", "renamed"
    additions: int = 0
    deletions: int = 0


class PRInfo(BaseModel):
    """Pull Request information."""

    repository: str
    number: int
    base_branch: str
    head_branch: str
    url: str


class ReviewerState(BaseModel):
    """State of a single reviewer."""

    status: Status = Status.PENDING
    findings_count: int = 0
    last_explored_depth: int = 0
    max_depth: int = 5


class PhaseStatus(BaseModel):
    """Status of each phase."""

    initialization: Status = Status.PENDING
    exploration: Status = Status.PENDING
    deep_analysis: Status = Status.PENDING  # Phase 1: Parallel review
    fix_pr_creation: Status = Status.PENDING  # Phase 2: Create draft PR
    fix_application: Status = Status.PENDING  # Phase 3: Sequential fix
    comment_posting: Status = Status.PENDING


class ReviewState(BaseModel):
    """Overall review state."""

    current_phase: Phase = Phase.INITIALIZATION
    phases: PhaseStatus = Field(default_factory=PhaseStatus)


class ExplorationItem(BaseModel):
    """An item in the exploration queue."""

    file: str
    reason: str  # "directly_changed", "calls_changed_method", etc.
    priority: int  # 1 = highest priority
    explored: bool = False
    depth: int = 0
    parent: str | None = None


class ExplorationCache(BaseModel):
    """Cache of explored items to avoid duplication."""

    explored_files: list[str] = Field(default_factory=list)
    explored_symbols: list[str] = Field(default_factory=list)
    call_graph: dict[str, list[str]] = Field(default_factory=dict)
    type_hierarchy: dict[str, list[str]] = Field(default_factory=dict)


class Finding(BaseModel):
    """A finding from a reviewer with phased fix tracking.

    Phase 1 (Review): source_file, source_line, title, description, scenario, fix_plan, fix_summary
    Phase 2 (PR Creation): number (assigned sequentially)
    Phase 3 (Fix Application): file, line, line_end, commit_hash
    """

    id: str
    reviewer: ReviewerType
    number: int | None = None  # Assigned in Phase 2 (sequential numbering)

    # Issue source location - Phase 1 output (where the problem was found)
    source_file: str
    source_line: int
    source_line_end: int | None = None

    # Problem description - Phase 1 output
    title: str
    description: str
    scenario: str | None = None  # Concrete scenario describing when the problem occurs
    fix_plan: str | None = None  # Plan for fixing the issue (Phase 1 output)
    fix_summary: str | None = None  # Brief 1-2 sentence summary of the fix (for display)

    # Fix location - Phase 3 output (where the fix was applied, for PR comment display)
    file: str | None = None
    line: int | None = None
    line_end: int | None = None

    # Fix result - Phase 3 output
    commit_hash: str | None = None  # Hash of the fix commit
    comment_url: str | None = None  # URL of the PR comment for this finding
    no_changes: bool = False  # True if fix was attempted but no changes needed


class Metadata(BaseModel):
    """Complete metadata for a PR review."""

    version: str = "1.0"
    pr: PRInfo
    started_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    status: Status = Status.IN_PROGRESS

    changed_files: list[ChangedFile] = Field(default_factory=list)
    review_state: ReviewState = Field(default_factory=ReviewState)

    reviewers: dict[ReviewerType, ReviewerState] = Field(default_factory=dict)

    exploration_queue: list[ExplorationItem] = Field(default_factory=list)
    exploration_cache: ExplorationCache = Field(default_factory=ExplorationCache)

    findings: list[Finding] = Field(default_factory=list)

    # Progress comment tracking (Phase 1で投稿したコメントのID)
    progress_comment_id: int | None = None

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        # Initialize all reviewers if not provided
        if not self.reviewers:
            self.reviewers = {rt: ReviewerState() for rt in ReviewerType}

    def update_timestamp(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now()

    def get_next_exploration_item(self) -> ExplorationItem | None:
        """Get the next unexplored item from the queue."""
        for item in sorted(self.exploration_queue, key=lambda x: x.priority):
            if not item.explored:
                return item
        return None

    def add_exploration_item(
        self,
        file: str,
        reason: str,
        priority: int,
        depth: int,
        parent: str | None = None,
    ) -> bool:
        """Add an item to the exploration queue if not already present."""
        if file in self.exploration_cache.explored_files:
            return False
        if any(item.file == file for item in self.exploration_queue):
            return False
        if depth > 5:  # Max depth
            return False

        self.exploration_queue.append(
            ExplorationItem(
                file=file,
                reason=reason,
                priority=priority,
                explored=False,
                depth=depth,
                parent=parent,
            )
        )
        return True

    def mark_explored(self, file: str) -> None:
        """Mark a file as explored."""
        for item in self.exploration_queue:
            if item.file == file:
                item.explored = True
                break
        if file not in self.exploration_cache.explored_files:
            self.exploration_cache.explored_files.append(file)

    def add_finding(self, finding: Finding) -> None:
        """Add a finding and update reviewer state."""
        self.findings.append(finding)
        if finding.reviewer in self.reviewers:
            self.reviewers[finding.reviewer].findings_count += 1

    def get_next_finding_id(self) -> str:
        """Generate the next finding ID."""
        return f"{len(self.findings) + 1:03d}"
