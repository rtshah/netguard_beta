"""Configuration: loads credentials and model/render settings from environment/.env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"

# Load .env from the project root if present.
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the extractor."""

    openai_api_key: str
    # A vision-capable model is required (we send page images).
    model: str = os.getenv("NETGUARD_MODEL", "gpt-4o")
    # Render resolution for page screenshots. Higher = sharper but larger payloads.
    render_dpi: int = int(os.getenv("NETGUARD_RENDER_DPI", "170"))
    # How many pages from the FRONT and the BACK to scan for the legend/metadata
    # (legends/keys often live in front matter or in an appendix at the end).
    legend_scan_pages: int = int(os.getenv("NETGUARD_LEGEND_PAGES", "10"))
    # Vertical padding (in PDF points) around a matched row when cropping a screenshot.
    row_crop_padding: float = float(os.getenv("NETGUARD_ROW_PADDING", "26"))
    # Max candidate pages to send to the LLM per drug (guards cost on noisy matches).
    max_pages_per_drug: int = int(os.getenv("NETGUARD_MAX_PAGES_PER_DRUG", "4"))


def load_config() -> Config:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to a .env file at the project root "
            "or export it in your shell."
        )
    OUTPUT_DIR.mkdir(exist_ok=True)
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    return Config(openai_api_key=key)
