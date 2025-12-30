"""Reviewer-specific prompts."""

from src.models import ReviewerType

from src.claude.reviewers.convention import PROMPT as CONVENTION
from src.claude.reviewers.efficiency import PROMPT as EFFICIENCY
from src.claude.reviewers.gc_allocation import PROMPT as GC_ALLOCATION
from src.claude.reviewers.impact_analysis import PROMPT as IMPACT_ANALYSIS
from src.claude.reviewers.resource_management import PROMPT as RESOURCE_MANAGEMENT
from src.claude.reviewers.runtime_error import PROMPT as RUNTIME_ERROR
from src.claude.reviewers.security import PROMPT as SECURITY
from src.claude.reviewers.unused_code import PROMPT as UNUSED_CODE
from src.claude.reviewers.wheel_reinvention import PROMPT as WHEEL_REINVENTION

REVIEWER_PROMPTS: dict[ReviewerType, str] = {
    ReviewerType.CONVENTION: CONVENTION,
    ReviewerType.EFFICIENCY: EFFICIENCY,
    ReviewerType.GC_ALLOCATION: GC_ALLOCATION,
    ReviewerType.IMPACT_ANALYSIS: IMPACT_ANALYSIS,
    ReviewerType.RESOURCE_MANAGEMENT: RESOURCE_MANAGEMENT,
    ReviewerType.RUNTIME_ERROR: RUNTIME_ERROR,
    ReviewerType.SECURITY: SECURITY,
    ReviewerType.UNUSED_CODE: UNUSED_CODE,
    ReviewerType.WHEEL_REINVENTION: WHEEL_REINVENTION,
}

__all__ = ["REVIEWER_PROMPTS"]
