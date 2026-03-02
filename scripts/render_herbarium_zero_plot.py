#!/usr/bin/env python3
"""Render a trend plot where herbarium 1950-2000 baseline is zero."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List


def linear_regression(xs: List[float], ys: List[float]) -> tuple[float, float]:
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    xbar = sum(xs) / n
    ybar = sum(ys) / n
    num = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
    den = sum((x - xbar) ** 2 for x in xs)
    if den == 0:
        return 0.0, ybar
    slope = num / den
    intercept = ybar - slope * xbar
    return slope, intercept


def save_svg(out_path: Path, years: List[int], values: List[float], slope: float, intercept: float) -> None:
    width, height = 980, 520
    margin = {"l": 80, "r": 30, "t": 40, "b": 70}
    plot_w = width - margin["l"] - margin["r"]
    plot_h = height - margin["t"] - margin["b"]
    y_min = min(values + [0.0]) - 3
    y_max = max(values + [0.0]) + 3
    if y_max <= y_min:
        y_max = y_min + 1

    def x_px(year: int) -> float:
        if len(years) == 1:
            return margin["l"] + plot_w / 2
        return margin["l"] + (year - years[0]) * (plot_w / (years[-1] - years[0]))

    def y_px(v: float) -> float:
        return margin["t"] + (y_max - v) * (plot_h / (y_max - y_min))

    points = " ".join(f"{x_px(y):.1f},{y_px(v):.1f}" for y, v in zip(years, values))
    trend_points = " ".join(
        f"{x_px(y):.1f},{y_px(intercept + slope * y):.1f}" for y in years
    )
    zero_y = y_px(0.0)

    y_ticks = 7
    y_tick_lines = []
    for i in range(y_ticks + 1):
        val = y_min + i * (y_max - y_min) / y_ticks
        py = y_px(val)
        y_tick_lines.append(
            f'<line x1="{margin["l"]}" y1="{py:.1f}" x2="{width-margin["r"]}" y2="{py:.1f}" stroke="#e7e2d8" stroke-width="1" />'
            f'<text x="{margin["l"]-10}" y="{py+4:.1f}" text-anchor="end" font-size="12" fill="#6b746c">{val:.1f}</text>'
        )

    x_labels = []
    for y in years:
        px = x_px(y)
        x_labels.append(
            f'<text x="{px:.1f}" y="{height-30}" text-anchor="middle" font-size="12" fill="#6b746c">{y}</text>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#fdfbf6"/>
  <text x="{width/2}" y="24" text-anchor="middle" font-size="20" font-family="Georgia, serif" fill="#233529">
    WA Baseline Trend Relative to Herbarium 1950-2000
  </text>
  {''.join(y_tick_lines)}
  <line x1="{margin["l"]}" y1="{zero_y:.1f}" x2="{width-margin["r"]}" y2="{zero_y:.1f}" stroke="#6b3fb0" stroke-width="2.2" />
  <polyline fill="none" stroke="#2c6a3f" stroke-width="3" points="{points}" />
  <polyline fill="none" stroke="#c46a3a" stroke-width="2.5" stroke-dasharray="7,5" points="{trend_points}" />
  {''.join(f'<circle cx="{x_px(y):.1f}" cy="{y_px(v):.1f}" r="4" fill="#2c6a3f"/>' for y, v in zip(years, values))}
  <line x1="{margin["l"]}" y1="{height-margin["b"]}" x2="{width-margin["r"]}" y2="{height-margin["b"]}" stroke="#7f8b83" />
  <line x1="{margin["l"]}" y1="{margin["t"]}" x2="{margin["l"]}" y2="{height-margin["b"]}" stroke="#7f8b83" />
  {''.join(x_labels)}
  <text x="{width/2}" y="{height-8}" text-anchor="middle" font-size="13" fill="#3f4c43">Year</text>
  <text x="22" y="{height/2}" transform="rotate(-90 22,{height/2})" text-anchor="middle" font-size="13" fill="#3f4c43">
    Mean anomaly (days) relative to herbarium baseline
  </text>
  <text x="{width-16}" y="{margin["t"]+18}" text-anchor="end" font-size="12" fill="#c46a3a">
    Trend slope: {slope:.2f} days/year
  </text>
  <text x="{width-16}" y="{margin["t"]+36}" text-anchor="end" font-size="12" fill="#6b3fb0">
    0 line = herbarium 1950-2000 baseline
  </text>
</svg>
"""
    out_path.write_text(svg, encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    summary = json.loads((root / "data" / "baseline_trend_summary.json").read_text(encoding="utf-8"))
    herb_mean = summary.get("herbarium_1950_2000_comparison", {}).get("mean_comparable_anomaly_days")
    if herb_mean is None:
        raise SystemExit("Missing herbarium comparison values. Run scripts/plot_baseline_trend.py first.")

    yearly = summary["yearly_aggregate"]
    years = [int(r["year"]) for r in yearly]
    shifted_vals = [float(r["mean_normalized_anomaly_days"]) - float(herb_mean) for r in yearly]
    slope, intercept = linear_regression([float(y) for y in years], shifted_vals)
    out = root / "data" / "baseline_trend_herbarium_zero.svg"
    save_svg(out, years, shifted_vals, slope=slope, intercept=intercept)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
