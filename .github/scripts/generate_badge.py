#!/usr/bin/env python3
"""Generate a coverage badge SVG from pytest-cov JSON output."""

import json
from pathlib import Path


def get_color(percentage: float) -> str:
    """Get badge color based on coverage percentage."""
    if percentage >= 90:
        return "#4c1"  # bright green
    elif percentage >= 80:
        return "#97ca00"  # green
    elif percentage >= 70:
        return "#a4a61d"  # yellow-green
    elif percentage >= 60:
        return "#dfb317"  # yellow
    elif percentage >= 50:
        return "#fe7d37"  # orange
    else:
        return "#e05d44"  # red


def generate_badge(percentage: float) -> str:
    """Generate SVG badge content."""
    color = get_color(percentage)
    percentage_text = f"{percentage:.0f}%"

    # Badge dimensions
    label_width = 60
    value_width = 45
    total_width = label_width + value_width

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20">
  <linearGradient id="b" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <mask id="a">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </mask>
  <g mask="url(#a)">
    <path fill="#555" d="M0 0h{label_width}v20H0z"/>
    <path fill="{color}" d="M{label_width} 0h{value_width}v20H{label_width}z"/>
    <path fill="url(#b)" d="M0 0h{total_width}v20H0z"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="{label_width / 2}" y="15" fill="#010101" fill-opacity=".3">coverage</text>
    <text x="{label_width / 2}" y="14">coverage</text>
    <text x="{label_width + value_width / 2}" y="15" fill="#010101" fill-opacity=".3">{percentage_text}</text>
    <text x="{label_width + value_width / 2}" y="14">{percentage_text}</text>
  </g>
</svg>'''


def main() -> None:
    """Main function to read coverage and generate badge."""
    coverage_file = Path("coverage.json")
    badge_dir = Path(".github/badges")
    badge_file = badge_dir / "coverage.svg"

    # Ensure badge directory exists
    badge_dir.mkdir(parents=True, exist_ok=True)

    # Read coverage data
    if not coverage_file.exists():
        print("Warning: coverage.json not found, using 0% coverage")
        percentage = 0.0
    else:
        with coverage_file.open() as f:
            data = json.load(f)
        percentage = data.get("totals", {}).get("percent_covered", 0.0)

    print(f"Coverage: {percentage:.1f}%")

    # Generate and write badge
    badge_svg = generate_badge(percentage)
    badge_file.write_text(badge_svg)
    print(f"Badge written to {badge_file}")


if __name__ == "__main__":
    main()
