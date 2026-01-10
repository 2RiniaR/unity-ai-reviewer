"""Reviewer registry for dynamic ReviewerType enum generation."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from src.reviewer_registry.loader import ReviewerInfo, scan_reviewers_directory

if TYPE_CHECKING:
    pass

# プロジェクトルートの reviewers/ ディレクトリ
REVIEWERS_DIR = Path(__file__).parent.parent.parent / "reviewers"


class ReviewerRegistry:
    """レビュワーの登録と管理を行うシングルトン"""

    _instance: ClassVar[ReviewerRegistry | None] = None
    _reviewers: dict[str, ReviewerInfo]
    _enum_class: type[Enum] | None

    def __init__(self) -> None:
        self._reviewers = {}
        self._enum_class = None

    @classmethod
    def instance(cls) -> ReviewerRegistry:
        """シングルトンインスタンスを取得"""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._load_reviewers()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """レジストリをリセット（テスト用）"""
        cls._instance = None

    def _load_reviewers(self) -> None:
        """reviewers/ ディレクトリをスキャンしてレビュワーを読み込む"""
        reviewers = scan_reviewers_directory(REVIEWERS_DIR)
        self._reviewers = {r.id: r for r in reviewers}

    def get_reviewer_info(self, reviewer_id: str) -> ReviewerInfo | None:
        """レビュワーIDから情報を取得"""
        return self._reviewers.get(reviewer_id)

    def get_all_reviewer_ids(self) -> list[str]:
        """全レビュワーIDのリストを取得"""
        return list(self._reviewers.keys())

    def get_all_reviewer_infos(self) -> list[ReviewerInfo]:
        """全レビュワー情報のリストを取得"""
        return list(self._reviewers.values())

    def get_display_name(self, reviewer_id: str) -> str:
        """レビュワーIDから表示名を取得"""
        info = self._reviewers.get(reviewer_id)
        return info.title if info else reviewer_id

    def get_prompt_content(self, reviewer_id: str) -> str | None:
        """レビュワーIDからプロンプト本文を取得"""
        info = self._reviewers.get(reviewer_id)
        return info.prompt_content if info else None

    def get_enum(self) -> type[Enum]:
        """動的に生成されたReviewerType Enumを返す"""
        if self._enum_class is not None:
            return self._enum_class

        # 動的Enumを生成
        enum_members = {
            info.id.upper(): info.id for info in self._reviewers.values()
        }

        # str を継承した Enum を作成
        base_enum = Enum(
            "ReviewerType",
            enum_members,
            type=str,
        )

        # display_name プロパティを追加
        registry = self

        def display_name_property(self: Enum) -> str:
            return registry.get_display_name(self.value)

        base_enum.display_name = property(display_name_property)  # type: ignore[attr-defined]

        self._enum_class = base_enum
        return self._enum_class
