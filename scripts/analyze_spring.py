#!/usr/bin/env python3
"""Estimate Washington spring timing from iNaturalist flowering observations."""

from __future__ import annotations

import json
import math
import re
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError

API_BASE = "https://api.inaturalist.org/v1"
WA_PLACE_ID = 46
FLOWERING_TERM_ID = 12
FLOWERING_VALUE_ID = 13
PER_PAGE = 200
CURRENT_DATE = date.today()
CURRENT_YEAR = CURRENT_DATE.year
BASELINE_START_YEAR = CURRENT_YEAR - 9
BASELINE_END_YEAR = CURRENT_YEAR - 1
MAX_RECORDS_PER_SPECIES = 1400

# Candidate native/common spring indicators spanning WA climates.
CANDIDATE_SPECIES = [
    "Oemleria cerasiformis",
    "Ribes sanguineum",
    "Mahonia aquifolium",
    "Trillium ovatum",
    "Camassia quamash",
    "Camassia leichtlinii",
    "Erythronium oregonum",
    "Claytonia sibirica",
    "Dicentra formosa",
    "Achlys triphylla",
    "Asarum caudatum",
    "Lysichiton americanus",
    "Tellima grandiflora",
    "Fritillaria affinis",
    "Acer macrophyllum",
    "Alnus rubra",
    "Amelanchier alnifolia",
    "Prunus emarginata",
    "Sambucus racemosa",
    "Vaccinium ovatum",
    "Balsamorhiza sagittata",
    "Lomatium utriculatum",
    "Viola glabella",
    "Ranunculus occidentalis",
]


@dataclass
class Observation:
    species: str
    taxon_id: int
    observed_on: date
    lat: float
    lon: float
    elev_m: Optional[float]
    uri: str
    photo_url: Optional[str]
    place_guess: Optional[str]


def fetch_json(endpoint: str, params: Dict[str, object], pause_s: float = 0.12) -> Dict:
    query = urllib.parse.urlencode(params)
    url = f"{API_BASE}/{endpoint}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "wa-spring-indicator/1.0"})

    attempt = 0
    while True:
        attempt += 1
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                payload = json.load(response)
            time.sleep(pause_s)
            return payload
        except HTTPError as err:
            if err.code == 429 and attempt < 7:
                delay = min(60.0, 2.0 * attempt)
                print(f"  - throttled by iNaturalist, retrying in {delay:.0f}s...", flush=True)
                time.sleep(delay)
                continue
            raise
        except URLError:
            if attempt < 5:
                delay = 1.5 * attempt
                time.sleep(delay)
                continue
            raise


def resolve_species_taxon(scientific_name: str) -> Optional[Dict]:
    payload = fetch_json(
        "taxa/autocomplete",
        {
            "q": scientific_name,
            "rank": "species",
            "is_active": "true",
            "per_page": 30,
        },
    )
    target = scientific_name.lower().strip()
    for result in payload.get("results", []):
        name = str(result.get("name", "")).lower().strip()
        rank = result.get("rank")
        if name == target and rank == "species":
            taxon_id = int(result["id"])
            default_photo = result.get("default_photo") or {}
            photo_url = (
                default_photo.get("medium_url")
                or default_photo.get("square_url")
                or default_photo.get("url")
            )
            return {
                "taxon_id": taxon_id,
                "common_name": result.get("preferred_common_name") or scientific_name,
                "taxon_url": f"https://www.inaturalist.org/taxa/{taxon_id}",
                "photo_url": photo_url,
            }
    return None


def parse_observation(raw: Dict, species: str, taxon_id: int) -> Optional[Observation]:
    observed_on = raw.get("observed_on")
    geojson = raw.get("geojson", {})
    if not observed_on or "coordinates" not in geojson:
        return None
    try:
        obs_date = datetime.strptime(observed_on, "%Y-%m-%d").date()
    except ValueError:
        return None
    coords = geojson.get("coordinates", [])
    if len(coords) != 2:
        return None
    lon, lat = coords
    elev = raw.get("elevation")
    try:
        elev_m = float(elev) if elev is not None else None
    except (TypeError, ValueError):
        elev_m = None
    return Observation(
        species=species,
        taxon_id=taxon_id,
        observed_on=obs_date,
        lat=float(lat),
        lon=float(lon),
        elev_m=elev_m,
        uri=str(raw.get("uri") or f"https://www.inaturalist.org/observations/{raw.get('id')}"),
        photo_url=(((raw.get("photos") or [{}])[0]).get("url") if raw.get("photos") else None),
        place_guess=raw.get("place_guess"),
    )


def fetch_species_observations(species: str, taxon_id: int) -> List[Observation]:
    observations: List[Observation] = []
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
                "d1": f"{BASELINE_START_YEAR}-01-01",
                "d2": f"{CURRENT_YEAR}-12-31",
                "order_by": "observed_on",
                "order": "asc",
                "per_page": PER_PAGE,
                "page": page,
            },
        )
        results = payload.get("results", [])
        for raw in results:
            parsed = parse_observation(raw, species, taxon_id)
            if parsed:
                observations.append(parsed)
        if not results or len(results) < PER_PAGE:
            break
        if len(observations) >= MAX_RECORDS_PER_SPECIES:
            break
        page += 1
    return observations


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "species"


def render_species_pages(project_root: Path, output: Dict) -> None:
    species_dir = project_root / "species"
    species_dir.mkdir(parents=True, exist_ok=True)
    for species in output["indicator_species"]:
        page_path = species_dir / f"{species['slug']}.html"
        photo_html = (
            f'<img src="{escape(species["photo_url"])}" alt="{escape(species["common_name"])}" '
            'style="max-width:100%;border-radius:12px;border:1px solid #ddd;" />'
            if species.get("photo_url")
            else '<div style="padding:1rem;background:#f3f3f3;border-radius:12px;">No photo available</div>'
        )
        obs_list = species.get("current_year_observations", [])
        if obs_list:
            links = "\n".join(
                (
                    f'<li><a href="{escape(obs["uri"])}" target="_blank" rel="noopener">'
                    f'{escape(obs["observed_on"])}'
                    f"{' - ' + escape(obs['place_guess']) if obs.get('place_guess') else ''}"
                    "</a></li>"
                )
                for obs in obs_list
            )
            obs_html = (
                "<p>This species has flowering observations this year.</p>"
                f"<ul>{links}</ul>"
            )
        else:
            obs_html = "<p>No current-year flowering observations in this dataset yet.</p>"

        year = output["years"]["current_year"]
        all_search_url = (
            f"https://www.inaturalist.org/observations?"
            f"place_id={WA_PLACE_ID}&taxon_id={species['taxon_id']}&quality_grade=research&"
            f"term_id={FLOWERING_TERM_ID}&term_value_id={FLOWERING_VALUE_ID}&"
            f"d1={year}-01-01&d2={year}-12-31"
        )
        html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(species['common_name'])} | WA Spring Bloom Watch</title>
  <style>
    body {{ margin: 0; font-family: Georgia, 'Times New Roman', serif; background:#f4f2ea; color:#1f2e22; }}
    .wrap {{ width:min(900px,92vw); margin:1.5rem auto 3rem; }}
    .card {{ background:#fffdf8; border:1px solid #ddd7c8; border-radius:16px; padding:1rem; }}
    .meta {{ color:#5e665f; }}
    a {{ color:#245f39; }}
  </style>
</head>
<body>
  <main class="wrap">
    <p><a href="../index.html">Back to dashboard</a></p>
    <section class="card">
      <h1>{escape(species['common_name'])}</h1>
      <p class="meta"><em>{escape(species['species'])}</em></p>
      {photo_html}
      <p class="meta">Status: <strong>{escape(species['status'])}</strong> | Anomaly: {species['anomaly_days']} days | Data granularity: {escape(species['granularity'])}</p>
      <p><a href="{escape(species['taxon_url'])}" target="_blank" rel="noopener">View taxon on iNaturalist</a></p>
      <p><a href="{escape(all_search_url)}" target="_blank" rel="noopener">View all {year} flowering observations in Washington</a></p>
      <h2>This Year's Flowering Observations</h2>
      {obs_html}
    </section>
  </main>
</body>
</html>
"""
        page_path.write_text(html, encoding="utf-8")


def percentile(values: List[float], p: float) -> float:
    if not values:
        raise ValueError("percentile() requires non-empty values")
    if len(values) == 1:
        return float(values[0])
    seq = sorted(values)
    idx = (len(seq) - 1) * p
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return float(seq[int(idx)])
    frac = idx - lo
    return float(seq[lo] * (1 - frac) + seq[hi] * frac)


def day_of_year(d: date) -> int:
    return d.timetuple().tm_yday


def cascade_divide_lon(lat: float) -> float:
    # Coarse linear approximation of Cascade crest longitude across WA.
    return -121.80 + (lat - 45.5) * 0.14


def side_of_cascades(lat: float, lon: float) -> str:
    return "east" if lon > cascade_divide_lon(lat) else "west"


def elevation_band(elev_m: Optional[float]) -> str:
    if elev_m is None:
        return "unknown"
    if elev_m < 500:
        return "low"
    if elev_m < 1200:
        return "mid"
    return "high"


def classify_status(anomaly_days: float) -> str:
    if anomaly_days <= -7:
        return "early"
    if anomaly_days >= 7:
        return "late"
    return "normal"


def summarize_species(
    species_name: str,
    common_name: str,
    taxon_id: int,
    taxon_url: str,
    photo_url: Optional[str],
    observations: List[Observation],
) -> Optional[Dict]:
    by_zone_year: Dict[str, Dict[int, List[int]]] = defaultdict(lambda: defaultdict(list))
    by_side_year: Dict[str, Dict[int, List[int]]] = defaultdict(lambda: defaultdict(list))
    by_state_year: Dict[int, List[int]] = defaultdict(list)
    current_obs_by_zone: Dict[str, int] = defaultdict(int)
    current_obs_by_side: Dict[str, int] = defaultdict(int)
    current_obs_state = 0
    current_obs_records: List[Observation] = []

    for obs in observations:
        side = side_of_cascades(obs.lat, obs.lon)
        zone = f"{side}-{elevation_band(obs.elev_m)}"
        doy = day_of_year(obs.observed_on)
        by_zone_year[zone][obs.observed_on.year].append(doy)
        by_side_year[side][obs.observed_on.year].append(doy)
        by_state_year[obs.observed_on.year].append(doy)
        if obs.observed_on.year == CURRENT_YEAR and obs.observed_on <= CURRENT_DATE:
            current_obs_by_zone[zone] += 1
            current_obs_by_side[side] += 1
            current_obs_state += 1
            current_obs_records.append(obs)

    def eval_groups(
        year_maps: Dict[str, Dict[int, List[int]]],
        current_obs_map: Dict[str, int],
        min_year_obs: int,
        min_baseline_years: int,
    ) -> List[Dict]:
        rows: List[Dict] = []
        today_doy = day_of_year(CURRENT_DATE)
        for group_name, year_map in year_maps.items():
            baseline_onsets: List[float] = []
            for year in range(BASELINE_START_YEAR, BASELINE_END_YEAR + 1):
                doys = year_map.get(year, [])
                if len(doys) >= min_year_obs:
                    baseline_onsets.append(percentile(doys, 0.2))
            current_doys = year_map.get(CURRENT_YEAR, [])
            if len(baseline_onsets) < min_baseline_years:
                continue
            baseline_doy = statistics.median(baseline_onsets)
            has_current = len(current_doys) >= 1
            if has_current:
                current_doy = percentile(current_doys, 0.2)
                anomaly = current_doy - baseline_doy
                status = classify_status(anomaly)
            else:
                current_doy = None
                anomaly = today_doy - baseline_doy
                status = "late" if anomaly >= 7 else "pending"
            rows.append(
                {
                    "zone": group_name,
                    "baseline_doy": round(baseline_doy, 1),
                    "current_doy": round(current_doy, 1) if current_doy is not None else None,
                    "anomaly_days": round(anomaly, 1),
                    "status": status,
                    "baseline_years": len(baseline_onsets),
                    "current_obs": current_obs_map.get(group_name, 0),
                    "has_current": has_current,
                }
            )
        return rows

    zone_results = eval_groups(
        by_zone_year,
        current_obs_by_zone,
        min_year_obs=3,
        min_baseline_years=4,
    )
    granularity = "zone"
    if not zone_results:
        zone_results = eval_groups(
            by_side_year,
            current_obs_by_side,
            min_year_obs=2,
            min_baseline_years=4,
        )
        granularity = "side"
    if not zone_results:
        zone_results = eval_groups(
            {"statewide": by_state_year},
            {"statewide": current_obs_state},
            min_year_obs=2,
            min_baseline_years=4,
        )
        granularity = "state"

    if not zone_results:
        return None

    weighted_anomaly_numer = 0.0
    weighted_anomaly_denom = 0.0
    has_current_zone = False
    has_late_without_current = False
    for zone in zone_results:
        if zone["has_current"]:
            has_current_zone = True
            weight = max(1, zone["baseline_years"]) * max(1, zone["current_obs"])
            weighted_anomaly_numer += zone["anomaly_days"] * weight
            weighted_anomaly_denom += weight
        elif zone["status"] == "late":
            has_late_without_current = True
            weight = max(1, zone["baseline_years"])
            weighted_anomaly_numer += zone["anomaly_days"] * weight
            weighted_anomaly_denom += weight

    species_anomaly = weighted_anomaly_numer / weighted_anomaly_denom if weighted_anomaly_denom else 0.0
    if has_current_zone:
        species_status = classify_status(species_anomaly)
    elif has_late_without_current:
        species_status = "late"
    else:
        species_status = "pending"
    return {
        "species": species_name,
        "slug": slugify(species_name),
        "common_name": common_name,
        "taxon_id": taxon_id,
        "taxon_url": taxon_url,
        "photo_url": photo_url,
        "status": species_status,
        "anomaly_days": round(species_anomaly, 2),
        "zones_used": len(zone_results),
        "granularity": granularity,
        "zones": sorted(zone_results, key=lambda z: abs(z["anomaly_days"]), reverse=True),
        "current_obs_total": current_obs_state,
        "has_current_data": has_current_zone,
        "current_year_observations": [
            {
                "observed_on": obs.observed_on.isoformat(),
                "uri": obs.uri,
                "place_guess": obs.place_guess,
                "photo_url": obs.photo_url,
            }
            for obs in sorted(current_obs_records, key=lambda r: r.observed_on, reverse=True)[:15]
        ],
    }


def pick_indicator_species(species_summaries: List[Dict], limit: int = 20) -> List[Dict]:
    granularity_rank = {"zone": 2, "side": 1, "state": 0}
    ranked = sorted(
        species_summaries,
        key=lambda s: (
            granularity_rank.get(s.get("granularity", "state"), 0),
            s["zones_used"],
            s["current_obs_total"],
            -abs(s["anomaly_days"]),
        ),
        reverse=True,
    )
    return ranked[:limit]


def build_zone_summary(indicators: List[Dict]) -> List[Dict]:
    zone_data: Dict[str, List[Tuple[float, int]]] = defaultdict(list)
    for species in indicators:
        for zone in species["zones"]:
            weight = max(1, zone["baseline_years"]) * max(1, zone["current_obs"])
            zone_data[zone["zone"]].append((zone["anomaly_days"], weight))
    rows = []
    for zone, values in zone_data.items():
        numer = sum(v * w for v, w in values)
        denom = sum(w for _, w in values)
        anomaly = numer / denom if denom else 0.0
        rows.append(
            {
                "zone": zone,
                "anomaly_days": round(anomaly, 2),
                "status": classify_status(anomaly),
                "species_count": len(values),
            }
        )
    return sorted(rows, key=lambda r: r["zone"])


def overall_status(indicators: List[Dict]) -> Dict:
    numer = 0.0
    denom = 0.0
    for species in indicators:
        if species.get("status") == "pending":
            continue
        weight = max(1, species["zones_used"]) * max(1, species["current_obs_total"])
        numer += species["anomaly_days"] * weight
        denom += weight
    anomaly = numer / denom if denom else 0.0
    return {
        "status": classify_status(anomaly),
        "anomaly_days": round(anomaly, 2),
        "species_count": len(indicators),
        "species_with_signal": sum(1 for s in indicators if s.get("status") != "pending"),
        "interpretation": (
            "Flowering is trending earlier than the 2017-2025 baseline."
            if anomaly <= -7
            else "Flowering is trending later than the 2017-2025 baseline."
            if anomaly >= 7
            else "Flowering is close to the 2017-2025 baseline."
        ),
    }


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    species_summaries: List[Dict] = []
    unresolved_species: List[str] = []

    for species in CANDIDATE_SPECIES:
        print(f"Resolving {species}...", flush=True)
        resolved = resolve_species_taxon(species)
        if not resolved:
            unresolved_species.append(species)
            print(f"  - unresolved", flush=True)
            continue
        taxon_id = resolved["taxon_id"]
        common_name = resolved["common_name"]
        taxon_url = resolved["taxon_url"]
        photo_url = resolved["photo_url"]
        print(f"  - fetching observations (taxon {taxon_id})", flush=True)
        observations = fetch_species_observations(species, taxon_id)
        summary = summarize_species(
            species,
            common_name,
            taxon_id,
            taxon_url,
            photo_url,
            observations,
        )
        if summary:
            summary["observation_count"] = len(observations)
            species_summaries.append(summary)
            print(f"  - usable: {len(observations)} observations, {summary['zones_used']} zones", flush=True)
        else:
            print(f"  - skipped: insufficient usable zone/year coverage ({len(observations)} observations)", flush=True)

    indicators = pick_indicator_species(species_summaries, limit=20)
    zones = build_zone_summary(indicators)
    overall = overall_status(indicators)

    output = {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "analysis_date": CURRENT_DATE.isoformat(),
        "wa_place_id": WA_PLACE_ID,
        "years": {
            "baseline_start": BASELINE_START_YEAR,
            "baseline_end": BASELINE_END_YEAR,
            "current_year": CURRENT_YEAR,
        },
        "method": {
            "flowering_filter": {
                "term_id": FLOWERING_TERM_ID,
                "term_value_id": FLOWERING_VALUE_ID,
            },
            "onset_metric": "20th percentile day-of-year of flowering observations",
            "status_threshold_days": 7,
            "geography_buckets": "east/west Cascade side plus elevation bands (low <500m, mid 500-1200m, high >1200m, unknown)",
            "notes": [
                "Based on iNaturalist research-grade flowering annotations in Washington.",
                "Observation effort is uneven across regions and species.",
                "Cascade split uses a coarse longitude approximation.",
            ],
        },
        "overall": overall,
        "zone_summary": zones,
        "indicator_species": indicators,
        "unresolved_species": unresolved_species,
    }

    json_path = data_dir / "spring_status.json"
    js_path = data_dir / "spring_status.js"
    json_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    js_path.write_text(
        "window.SPRING_STATUS = " + json.dumps(output, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    render_species_pages(project_root, output)
    print(f"Wrote {json_path}")
    print(f"Wrote {js_path}")
    print(
        f"Overall: {overall['status']} ({overall['anomaly_days']} days), "
        f"{overall['species_count']} indicator species"
    )


if __name__ == "__main__":
    main()
