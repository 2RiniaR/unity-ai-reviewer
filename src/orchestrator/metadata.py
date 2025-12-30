"""Metadata file handling for PR reviews."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.models import Metadata, PRInfo


class MetadataHandler:
    """Handles reading and writing metadata files."""

    def __init__(self, reviews_dir: Path) -> None:
        """Initialize the metadata handler.

        Args:
            reviews_dir: Directory where review data is stored
        """
        self.reviews_dir = reviews_dir
        self.reviews_dir.mkdir(parents=True, exist_ok=True)

    def get_current_review_path(self) -> Path | None:
        """Get the path to the current active review."""
        current_file = self.reviews_dir / ".current-review"
        if current_file.exists():
            folder_name = current_file.read_text().strip()
            review_path = self.reviews_dir / folder_name
            if review_path.exists():
                return review_path
        return None

    def set_current_review(self, folder_name: str) -> None:
        """Set the current active review."""
        current_file = self.reviews_dir / ".current-review"
        current_file.write_text(folder_name)

    def create_review(self, pr_info: PRInfo) -> tuple[Path, Metadata]:
        """Create a new review folder and metadata.

        Args:
            pr_info: Pull request information

        Returns:
            Tuple of (review folder path, metadata object)
        """
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        folder_name = f"{pr_info.number}-{timestamp}"
        review_path = self.reviews_dir / folder_name
        review_path.mkdir(parents=True, exist_ok=True)

        # Create metadata
        metadata = Metadata(pr=pr_info)
        self.save_metadata(review_path, metadata)
        self.set_current_review(folder_name)

        return review_path, metadata

    def load_metadata(self, review_path: Path) -> Metadata:
        """Load metadata from a review folder.

        Args:
            review_path: Path to the review folder

        Returns:
            Metadata object
        """
        metadata_file = review_path / "metadata.json"
        if not metadata_file.exists():
            raise FileNotFoundError(f"Metadata file not found: {metadata_file}")

        with open(metadata_file) as f:
            data = json.load(f)

        return Metadata.model_validate(data)

    def save_metadata(self, review_path: Path, metadata: Metadata) -> None:
        """Save metadata to a review folder.

        Args:
            review_path: Path to the review folder
            metadata: Metadata object to save
        """
        metadata.update_timestamp()
        metadata_file = review_path / "metadata.json"

        with open(metadata_file, "w") as f:
            json.dump(
                metadata.model_dump(mode="json"),
                f,
                indent=2,
                ensure_ascii=False,
                default=self._json_serializer,
            )

    def _json_serializer(self, obj: Any) -> Any:
        """Custom JSON serializer for special types."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Path):
            return str(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
