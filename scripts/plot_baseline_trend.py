#!/usr/bin/env python3
"""Compute and plot baseline-year bloom onset trend across indicator species."""

from __future__ import annotations

import csv
import io
import json
import math
import socket
import time
from datetime import datetime
from pathlib import Path
from statistics import median, stdev
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from analyze_spring import (
    FLOWERING_TERM_ID,
    FLOWERING_VALUE_ID,
    PER_PAGE,
    WA_PLACE_ID,
    fetch_json,
    parse_observation,
    percentile,
)

MIN_OBS_PER_YEAR = 3
MAX_RECORDS_PER_SPECIES = 2000
HERBARIUM_BASE = "https://www.pnwherbaria.org/data/results.php"


def fetch_species_observations_for_baseline(
    species_name: str, taxon_id: int, d1: str, d2: str
) -> List:
    observations = []
    page = 1
    while True:
        payload = fetch_json(
            "observations",
            {
                "taxon_id": taxon_id,
                "place_id": WA_PLACE_ID,
                "quality_grade": "research",
                "iconic_taxa": "Plantae",
                "term_id": FLOWERING_TERM_ID,
                "term_value_id": FLOWERING_VALUE_ID,
                "d1": d1,
                "d2": d2,
                "order_by": "observed_on",
                "order": "asc",
                "per_page": PER_PAGE,
                "page": page,
            },
        )
        results = payload.get("results", [])
        for raw in results:
            parsed = parse_observation(raw, species_name, taxon_id)
            if parsed:
                observations.append(parsed)
        if not results or len(results) < PER_PAGE or len(observations) >= MAX_RECORDS_PER_SPECIES:
            break
        page += 1
    return observations


def linear_regression(xs: List[float], ys: List[float]) -> Tuple[float, float]:
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


def fetch_herbarium_flowering_doys(
    species_name: str,
    state: str = "WA",
    start_year: int = 1950,
    end_year: int = 2000,
) -> List[int]:
    parts = species_name.split()
    if len(parts) < 2:
        return []
    genus, epithet = parts[0], parts[1]
    params = {
        "DisplayAs": "Text",
        "TextFileType": "Tab",
        "ExcludeCultivated": "Y",
        "SearchAllHerbaria": "Y",
        "GroupBy": "ungrouped",
        "SortBy": "Year",
        "SortOrder": "ASC",
        "QueryCount": 1,
        "Genus1": genus,
        "Species1": epithet,
        "IncludeSynonyms1": "Y",
        "State1": state,
    }
    url = f"{HERBARIUM_BASE}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "wa-spring-indicator/1.0"})
    with urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    doys: List[int] = []
    for row in reader:
        phen = (row.get("Phenology") or "").strip().lower()
        if "flower" not in phen:
            continue
        try:
            day = int((row.get("Day Collected") or "").strip())
            month = int((row.get("Month Collected") or "").strip())
            year = int((row.get("Year Collected") or "").strip())
        except ValueError:
            continue
        if year < start_year or year > end_year:
            continue
        try:
            dt = datetime(year, month, day)
        except ValueError:
            continue
        doys.append(int(dt.timetuple().tm_yday))
    return doys


def save_svg_plot(
    out_path: Path,
    years: List[int],
    values: List[float],
    slope: float,
    intercept: float,
    herbarium_line: Optional[float] = None,
) -> None:
    width, height = 980, 520
    margin = {"l": 80, "r": 30, "t": 40, "b": 70}
    plot_w = width - margin["l"] - margin["r"]
    plot_h = height - margin["t"] - margin["b"]
    bounds = values + [0.0]
    if herbarium_line is not None:
        bounds.append(herbarium_line)
    y_min = min(bounds) - 3
    y_max = max(bounds) + 3
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
    herb_y = y_px(herbarium_line) if herbarium_line is not None else None

    y_ticks = 7
    y_tick_lines = []
    for i in range(y_ticks + 1):
        val = y_min + i * (y_max - y_min) / y_ticks
        py = y_px(val)
        y_tick_lines.append(
            f'<line x1="{margin["l"]}" y1="{py:.1f}" x2="{width-margin["r"]}" y2="{py:.1f}" '
            f'stroke="#e7e2d8" stroke-width="1" />'
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
    WA Baseline Trend (Species-Normalized Bloom Onset)
  </text>
  {''.join(y_tick_lines)}
  <line x1="{margin["l"]}" y1="{zero_y:.1f}" x2="{width-margin["r"]}" y2="{zero_y:.1f}" stroke="#98a59b" stroke-width="1.2" />
  <polyline fill="none" stroke="#2c6a3f" stroke-width="3" points="{points}" />
  <polyline fill="none" stroke="#c46a3a" stroke-width="2.5" stroke-dasharray="7,5" points="{trend_points}" />
  {f'<line x1="{margin["l"]}" y1="{herb_y:.1f}" x2="{width-margin["r"]}" y2="{herb_y:.1f}" stroke="#6b3fb0" stroke-width="2.5" stroke-dasharray="4,4" />' if herb_y is not None else ''}
  {''.join(f'<circle cx="{x_px(y):.1f}" cy="{y_px(v):.1f}" r="4" fill="#2c6a3f"/>' for y, v in zip(years, values))}
  <line x1="{margin["l"]}" y1="{height-margin["b"]}" x2="{width-margin["r"]}" y2="{height-margin["b"]}" stroke="#7f8b83" />
  <line x1="{margin["l"]}" y1="{margin["t"]}" x2="{margin["l"]}" y2="{height-margin["b"]}" stroke="#7f8b83" />
  {''.join(x_labels)}
  <text x="{width/2}" y="{height-8}" text-anchor="middle" font-size="13" fill="#3f4c43">Year</text>
  <text x="22" y="{height/2}" transform="rotate(-90 22,{height/2})" text-anchor="middle" font-size="13" fill="#3f4c43">
    Mean anomaly (days, species-normalized)
  </text>
  <text x="{width-16}" y="{margin["t"]+18}" text-anchor="end" font-size="12" fill="#c46a3a">
    Trend slope: {slope:.2f} days/year
  </text>
  {f'<text x="{width-16}" y="{margin["t"]+36}" text-anchor="end" font-size="12" fill="#6b3fb0">1950-2000 herbarium baseline: {herbarium_line:.2f} days</text>' if herbarium_line is not None else ''}
</svg>
"""
    out_path.write_text(svg, encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    data_path = root / "data" / "spring_status.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    years = data["years"]
    baseline_start = years["baseline_start"]
    baseline_end = years["baseline_end"]
    baseline_years = list(range(baseline_start, baseline_end + 1))

    species_rows = data["indicator_species"]
    per_species_year_onset: Dict[str, Dict[int, float]] = {}
    species_meta: Dict[str, Dict] = {}

    d1 = f"{baseline_start}-01-01"
    d2 = f"{baseline_end}-12-31"

    for species in species_rows:
        sci = species["species"]
        taxon_id = int(species["taxon_id"])
        print(f"Fetching baseline years for {sci} ({taxon_id})...", flush=True)
        observations = []
        for attempt in range(1, 5):
            try:
                observations = fetch_species_observations_for_baseline(sci, taxon_id, d1=d1, d2=d2)
                break
            except (socket.timeout, TimeoutError):
                if attempt >= 4:
                    raise
                delay = attempt * 3
                print(f"  - timeout, retrying in {delay}s...", flush=True)
                time.sleep(delay)
        by_year: Dict[int, List[int]] = {}
        for obs in observations:
            yr = obs.observed_on.year
            by_year.setdefault(yr, []).append(obs.observed_on.timetuple().tm_yday)

        onset_by_year: Dict[int, float] = {}
        for y in baseline_years:
            doys = by_year.get(y, [])
            if len(doys) >= MIN_OBS_PER_YEAR:
                onset_by_year[y] = float(percentile(doys, 0.2))
        if len(onset_by_year) >= 5:
            per_species_year_onset[sci] = onset_by_year
            species_meta[sci] = {
                "taxon_id": taxon_id,
                "common_name": species["common_name"],
            }

    # Normalize by species median onset over baseline period.
    normalized_rows = []
    for sci, yearly in per_species_year_onset.items():
        vals = [yearly[y] for y in sorted(yearly)]
        med = median(vals)
        sd = stdev(vals) if len(vals) > 1 else 0.0
        for y, onset in yearly.items():
            anomaly = onset - med
            z = (anomaly / sd) if sd > 0 else 0.0
            normalized_rows.append(
                {
                    "species": sci,
                    "common_name": species_meta[sci]["common_name"],
                    "taxon_id": species_meta[sci]["taxon_id"],
                    "year": y,
                    "onset_doy": round(onset, 3),
                    "species_median_doy": round(med, 3),
                    "anomaly_days": round(anomaly, 3),
                    "zscore": round(z, 3),
                }
            )

    # Aggregate by year.
    agg_by_year = {}
    for y in baseline_years:
        rows = [r for r in normalized_rows if r["year"] == y]
        if not rows:
            continue
        mean_anom = sum(r["anomaly_days"] for r in rows) / len(rows)
        mean_z = sum(r["zscore"] for r in rows) / len(rows)
        agg_by_year[y] = {
            "year": y,
            "species_count": len(rows),
            "mean_normalized_anomaly_days": round(mean_anom, 3),
            "mean_zscore": round(mean_z, 3),
        }

    agg_years = sorted(agg_by_year)
    agg_vals = [agg_by_year[y]["mean_normalized_anomaly_days"] for y in agg_years]
    slope, intercept = linear_regression([float(y) for y in agg_years], agg_vals)

    # Herbarium (1950-2000) baseline in comparable anomaly units:
    # species-level herbarium onset (20th percentile DOY, flowering only)
    # minus iNaturalist 2017-2025 species median onset.
    species_recent_medians = {
        sci: median([per_species_year_onset[sci][y] for y in per_species_year_onset[sci]])
        for sci in per_species_year_onset
    }
    herbarium_rows = []
    for sci in per_species_year_onset:
        for attempt in range(1, 5):
            try:
                herb_doys = fetch_herbarium_flowering_doys(sci, start_year=1950, end_year=2000)
                break
            except (socket.timeout, TimeoutError):
                if attempt >= 4:
                    raise
                delay = attempt * 3
                print(f"  - herbarium timeout for {sci}, retrying in {delay}s...", flush=True)
                time.sleep(delay)
        else:
            herb_doys = []
        if len(herb_doys) < 5:
            continue
        herb_onset = float(percentile(herb_doys, 0.2))
        anomaly = herb_onset - float(species_recent_medians[sci])
        herbarium_rows.append(
            {
                "species": sci,
                "common_name": species_meta[sci]["common_name"],
                "taxon_id": species_meta[sci]["taxon_id"],
                "herbarium_flowering_obs_1950_2000": len(herb_doys),
                "herbarium_onset_doy_20pct": round(herb_onset, 3),
                "inat_2017_2025_median_onset_doy": round(float(species_recent_medians[sci]), 3),
                "comparable_anomaly_days": round(anomaly, 3),
            }
        )
    herbarium_line = None
    if herbarium_rows:
        herbarium_line = sum(r["comparable_anomaly_days"] for r in herbarium_rows) / len(herbarium_rows)

    out_csv = root / "data" / "baseline_normalized_onsets.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "species",
                "common_name",
                "taxon_id",
                "year",
                "onset_doy",
                "species_median_doy",
                "anomaly_days",
                "zscore",
            ],
        )
        writer.writeheader()
        writer.writerows(sorted(normalized_rows, key=lambda r: (r["species"], r["year"])))

    out_summary = root / "data" / "baseline_trend_summary.json"
    summary = {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseline_years": {"start": baseline_start, "end": baseline_end},
        "species_used": len(per_species_year_onset),
        "yearly_aggregate": [agg_by_year[y] for y in agg_years],
        "linear_trend": {
            "slope_days_per_year": round(slope, 4),
            "intercept": round(intercept, 4),
        },
        "herbarium_1950_2000_comparison": {
            "species_used": len(herbarium_rows),
            "mean_comparable_anomaly_days": round(herbarium_line, 4) if herbarium_line is not None else None,
            "notes": "Computed from CPNWH WA records with Phenology containing 'flower'; species onset metric is 20th percentile DOY over 1950-2000 records.",
        },
    }
    out_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    out_herbarium_csv = root / "data" / "herbarium_1950_2000_comparison.csv"
    with out_herbarium_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "species",
                "common_name",
                "taxon_id",
                "herbarium_flowering_obs_1950_2000",
                "herbarium_onset_doy_20pct",
                "inat_2017_2025_median_onset_doy",
                "comparable_anomaly_days",
            ],
        )
        writer.writeheader()
        writer.writerows(sorted(herbarium_rows, key=lambda r: r["species"]))

    out_svg = root / "data" / "baseline_trend.svg"
    save_svg_plot(
        out_svg,
        agg_years,
        agg_vals,
        slope=slope,
        intercept=intercept,
        herbarium_line=herbarium_line,
    )

    print(f"Wrote {out_csv}")
    print(f"Wrote {out_summary}")
    print(f"Wrote {out_herbarium_csv}")
    print(f"Wrote {out_svg}")
    print(
        "Trend slope (days/year): "
        f"{slope:.3f} "
        f"({'later' if slope > 0 else 'earlier' if slope < 0 else 'flat'})"
    )
    if herbarium_line is not None:
        print(
            "Herbarium 1950-2000 comparable anomaly: "
            f"{herbarium_line:.3f} days "
            f"({'later' if herbarium_line > 0 else 'earlier' if herbarium_line < 0 else 'same'})"
        )


if __name__ == "__main__":
    main()
