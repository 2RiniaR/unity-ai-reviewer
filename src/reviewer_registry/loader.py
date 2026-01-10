"""Markdown file loader for reviewer prompts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class ReviewerInfo:
    """レビュワー情報を保持するデータクラス"""

    id: str  # ファイル名（拡張子なし）: "runtime_error"
    title: str  # フロントマターのtitle: "実行時エラー"
    prompt_path: Path  # Markdownファイルのパス
    prompt_content: str  # プロンプト本文（フロントマター除く）


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Markdownファイルからフロントマターを解析

    Args:
        content: Markdownファイルの内容

    Returns:
        (frontmatter_dict, body) タプル
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        frontmatter = {}

    body = parts[2].lstrip("\n")
    return frontmatter, body


def load_reviewer_from_file(file_path: Path) -> ReviewerInfo:
    """Markdownファイルからレビュワー情報を読み込む

    Args:
        file_path: Markdownファイルのパス

    Returns:
        ReviewerInfo オブジェクト
    """
    content = file_path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(content)

    reviewer_id = file_path.stem
    title = frontmatter.get("title", reviewer_id)

    return ReviewerInfo(
        id=reviewer_id,
        title=title,
        prompt_path=file_path,
        prompt_content=body,
    )


def scan_reviewers_directory(directory: Path) -> list[ReviewerInfo]:
    """reviewers/ ディレクトリをスキャンしてレビュワー情報を取得

    Args:
        directory: reviewers/ ディレクトリのパス

    Returns:
        ReviewerInfo のリスト
    """
    if not directory.exists():
        return []

    reviewers = []
    for file_path in sorted(directory.glob("*.md")):
        reviewers.append(load_reviewer_from_file(file_path))

    return reviewers
