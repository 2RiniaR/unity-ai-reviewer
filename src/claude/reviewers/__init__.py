"""Reviewer-specific prompts."""

from src.models import ReviewerType
from src.claude.prompt_loader import get_all_reviewer_prompts

# 後方互換性のため REVIEWER_PROMPTS 辞書を維持
REVIEWER_PROMPTS: dict[ReviewerType, str] = get_all_reviewer_prompts()

__all__ = ["REVIEWER_PROMPTS"]
