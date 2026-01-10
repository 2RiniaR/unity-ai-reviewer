"""Prompt loader for reviewer prompts from Markdown files."""

from __future__ import annotations

from enum import Enum

from src.reviewer_registry import ReviewerRegistry, get_reviewer_type


class PromptNotFoundError(Exception):
    """Raised when a prompt file is not found."""

    pass


def load_reviewer_prompt(reviewer_type: Enum) -> str:
    """Load a reviewer prompt from registry.

    Args:
        reviewer_type: Type of reviewer (ReviewerType enum member)

    Returns:
        Prompt content as string (without frontmatter)

    Raises:
        PromptNotFoundError: If prompt is not found
    """
    content = ReviewerRegistry.instance().get_prompt_content(reviewer_type.value)
    if content is None:
        raise PromptNotFoundError(
            f"Prompt not found for reviewer: {reviewer_type.value}\n"
            f"Expected file: reviewers/{reviewer_type.value}.md"
        )
    return content


def get_all_reviewer_prompts() -> dict:
    """Load all reviewer prompts.

    Returns:
        Dictionary mapping ReviewerType to prompt content
    """
    ReviewerType = get_reviewer_type()
    return {rt: load_reviewer_prompt(rt) for rt in ReviewerType}


def validate_all_prompts() -> None:
    """Validate all prompt files exist at startup.

    This is now effectively a no-op since ReviewerRegistry only loads
    valid reviewers from existing Markdown files.
    """
    # ReviewerRegistry already handles this during initialization
    pass
