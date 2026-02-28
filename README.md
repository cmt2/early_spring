# Washington Spring Bloom Watch

This project estimates whether Washington's spring is **early**, **normal**, or **late** based on iNaturalist flowering observations.

## What it does

- Uses iNaturalist observations in Washington (`place_id=46`) with flowering annotation (`term_id=12`, `term_value_id=13`)
- Uses the past 10 years of data (current year plus prior 9 years)
- Estimates a normal bloom onset for each species by:
  - East vs west of the Cascades (approximate divide)
  - Elevation band (`low <500m`, `mid 500-1200m`, `high >1200m`, `unknown`)
- Selects ~20 indicator species from a larger candidate pool based on usable geographic coverage and current-year data
- Produces a statewide spring status and zone-level statuses
- Marks species as `pending` when they have robust baseline history but no current-year flowering observations yet

## How "Normal Bloom Onset" Is Estimated

This project uses a robust onset metric designed to be less sensitive to outlier early observations.

1. For each species and geography group, collect flowering observations by year.
2. For each year, compute that year's bloom onset as the **20th percentile day-of-year (DOY)** of flowering observations.
   - Example: if most flowers are seen in April but a few are seen in March, the 20th percentile is earlier than median but less noisy than minimum date.
3. Build the baseline from the prior 9 years (currently `2017-2025` when current year is `2026`):
   - Baseline onset = **median** of yearly onset values across baseline years.
4. Compute current-year onset the same way (20th percentile DOY), then:
   - `anomaly_days = current_onset_doy - baseline_onset_doy`
   - Negative anomaly means earlier than normal.

### Geography handling

Bloom timing is estimated separately by geography bucket:

- Cascade side: `east` or `west` (coarse longitude approximation of Cascade crest)
- Elevation band:
  - `low` `<500m`
  - `mid` `500-1200m`
  - `high` `>1200m`
  - `unknown` (no elevation in record)

Primary analysis uses `side + elevation` zones.  
If that is too sparse for a species, it falls back to:

1. `side` only (`east` / `west`)
2. `statewide`

### Data sufficiency rules

- A baseline year contributes only if it has at least a minimum number of observations in that group.
- A species/group is kept only if it has enough baseline years (minimum coverage requirement).
- This avoids unstable baselines from very sparse records.

### Status thresholds

Species and aggregate spring status use these anomaly cutoffs:

- `early`: anomaly `<= -7` days
- `normal`: between `-7` and `+7` days
- `late`: anomaly `>= +7` days

If no current-year flowering observations exist for a species:

- `pending` if we are not yet past expected bloom onset
- `late` if current date is already sufficiently past expected onset

### Aggregation

- Group-level anomalies are combined to species-level with weighted averaging.
- Species-level anomalies are combined into overall Washington status with weighting by data support.
- The dashboard also reports how many indicator species currently have a live-year bloom signal.

## Run

```bash
python3 scripts/analyze_spring.py
```

Outputs:

- `data/spring_status.json`
- `data/spring_status.js`
- `species/*.html` (one detail page per indicator species with photo and iNaturalist links)

Open `index.html` in a browser after generating data.

## Publish On GitHub Pages

1. Create a new empty GitHub repository (for example `wa-spring-bloom-watch`).
2. From this project folder:

```bash
git init
git branch -M main
git add .
git commit -m "Initial spring bloom site"
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

3. In GitHub repo settings:
   - Go to `Settings` -> `Pages`
   - Set `Build and deployment` source to `GitHub Actions`
4. After the `Deploy GitHub Pages` workflow succeeds, your site will be live at:
   - `https://<your-username>.github.io/<your-repo>/`

## Automatic Daily Refresh

- The workflow `.github/workflows/refresh-data.yml` runs daily and can also be run manually.
- It regenerates:
  - `data/spring_status.json`
  - `data/spring_status.js`
  - `species/*.html`
- If files changed, it commits to `main`, which triggers Pages redeploy.
- The homepage shows `Last updated` using the dataset `generated_at` timestamp.

## Notes

- This approach depends on observer effort and annotation behavior.
- Some species/regions have sparse data in a given year.
- Cascade split is a coarse approximation; if needed this can be replaced with a true watershed/terrain boundary.
