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

## Notes

- This approach depends on observer effort and annotation behavior.
- Some species/regions have sparse data in a given year.
- Cascade split is a coarse approximation; if needed this can be replaced with a true watershed/terrain boundary.
