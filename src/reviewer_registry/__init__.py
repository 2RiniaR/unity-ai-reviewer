"""Reviewer registry module for dynamic ReviewerType management."""

from __future__ import annotations

from enum import Enum

from src.reviewer_registry.loader import ReviewerInfo
from src.reviewer_registry.registry import ReviewerRegistry

__all__ = [
    "ReviewerInfo",
    "ReviewerRegistry",
    "get_reviewer_type",
    "get_all_reviewer_ids",
    "get_display_name",
    "get_prompt_content",
]


def get_reviewer_type() -> type[Enum]:
    """動的に生成されたReviewerType Enumを取得

    Returns:
        ReviewerType Enum クラス
    """
    return ReviewerRegistry.instance().get_enum()


def get_all_reviewer_ids() -> list[str]:
    """全レビュワーIDのリストを取得

    Returns:
        レビュワーIDのリスト
    """
    return ReviewerRegistry.instance().get_all_reviewer_ids()


def get_display_name(reviewer_id: str) -> str:
    """レビュワーIDから表示名を取得

    Args:
        reviewer_id: レビュワーID

    Returns:
        日本語表示名
    """
    return ReviewerRegistry.instance().get_display_name(reviewer_id)


def get_prompt_content(reviewer_id: str) -> str | None:
    """レビュワーIDからプロンプト本文を取得

    Args:
        reviewer_id: レビュワーID

    Returns:
        プロンプト本文（フロントマター除く）
    """
    return ReviewerRegistry.instance().get_prompt_content(reviewer_id)
