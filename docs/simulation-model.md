# Simulation model discussion — Issue #11

Status: **DRAFT — under discussion, nothing is final yet.**

This document proposes a modeling approach for estimating `deaths` and
`damage_usd` of a simulated asteroid impact on a city, and lists the open
questions the team must settle before we implement anything. Nothing here is
challenged as "decided" until the team signs it off.

The goal is an **order-of-magnitude estimate**, not an exact physics
simulation. Consequences per event = deaths + material damage, in the same
units as the historical disasters we load from EM-DAT, so the game can compare
the two.

## 1. Key finding: no single library does it all

We surveyed available tools. **None of the verifiable sources provide a
ready-made Python library that takes Sentry data plus coordinates and returns
both deaths and damage in USD.** We must compose several model layers, and the
economic-loss layer in particular is on us.

| Candidate | What it provides | What is missing | Verdict for us |
|---|---|---|---|
| `ImpactEffect` (PyPI) | Physical effects of the impact (airburst altitude, peak overpressure, max wind velocity, etc.) at a distance from impact | No casualty pipeline, no monetary loss | Good candidate for the **physics layer**; must be smoke-tested before we commit |
| Rumpf vulnerability models (`c-type/asteroid_impact_vulnerability`) | Fatality fraction of a population exposed to a given level of each effect (wind, overpressure, thermal, cratering, seismic shaking, ejecta) | Needs physical effects + spatial population as inputs; no USD | Closest verified match for the **deaths layer** |
| ARMOR (Rumpf et al. 2017) | Full research framework: probability + effects + population + vulnerability | No installable package verified | Methodological reference only; do not plan around `pip install armor` |
| GEM Global Exposure Model | Building counts, occupants, replacement costs per ~1 km cell (residential / commercial / industrial) | Not an asteroid model; no damage ratios | Candidate source for the **exposure layer** (population and assets) |
| OpenQuake | Structural/non-structural/contents loss and casualties for scenario risk | Needs exposure + vulnerability matched to a shaking field; does not handle blast/thermal | Overkill for MVP; possible later extension for the seismic branch only |
| pelicun | Python damage/loss framework (FEMA P-58 based) | We must supply demand, fragility, consequence models | Possible later upgrade for the loss layer |
| NASA PAIR | Probabilistic risk over many scenarios | No ready Python API; "affected population" is not deaths | Methodological reference for limitations |
| Purdue Impact: Earth! | The reference implementation `ImpactEffect` reimplements | Web calculator, not a library | Used as **validation benchmark** for our physics outputs |

## 2. Proposed architecture: three composed layers

```
Asteroid (diameter, mass, v_imp, density) + scenario assumptions
                     |
                     v
   [1. PHYSICS]  ImpactEffect  -> effect intensities per distance
                     |
                     v
   [2. FATALITY] Rumpf models  -> deaths per cell, combined
                     |
                     v
   [3. ECONOMIC]  exposure x loss ratios -> damage_usd
                     |
                     v
     fact_event_toll row (origin = 'Simulated')
```

Each layer sits behind its own thin Python adapter, so we can swap
`ImpactEffect`, retune the fatality model, or upgrade the loss model without
touching the Airflow orchestration.

### 2.1 Physics layer — `ImpactEffect`

- PyPI: `ImpactEffect==1.0.0` (2022-09-15, Python >= 3.7, MIT license).
  Reimplements the Purdue Earth Impact Effects Program (Melosh et al.).
- **What it gives us**: overpressure, wind velocity, thermal radiation,
  airburst altitude, crater size, seismic magnitude — as functions of distance
  from the impact point.
- **What it does not give us**: no `estimate_deaths()` function, and its
  "damage" descriptions ("glass windows may shatter") are not USD values.
- Doc examples show some import inconsistencies, so we write our own adapter,
  pin the version, and **cross-check a few scenarios against the Purdue web
  calculator before wiring it into Airflow**.

### 2.2 Deaths layer — Rumpf vulnerability models

- Repo: `c-type/asteroid_impact_vulnerability` (published by Clemens Rumpf
  himself, 2018-05-29, Python). Paper: *Population vulnerability models for
  asteroid impact risk assessment*, Rumpf, Lewis & Atkinson 2017,
  DOI 10.1111/maps.12861.
- Structure: split the area around the impact into population cells; for each
  cell `i` and each hazard `h` (wind, overpressure, thermal, shaking, ejecta,
  cratering):

  ```
  D_i = N_i * V_i        with        V_i = 1 - prod_h (1 - V_i,h)
  D   = sum_i D_i
  ```

  The product-of-survival form avoids double-counting a person killed by both
  wind and heat. Note this independence assumption is itself a modeling
  choice, not a proven fact.
- **Stated limits we must respect**: the models were derived from tornado and
  nuclear-blast data; the author used them for asteroids up to ~400 m diameter.
  The published code does not include the tsunami effect from the paper.
  Several of our Sentry asteroids exceed 400 m — we must decide how to label
  those results (extrapolation warning).
- **License check needed**: the repo shows no clear license. Before copying or
  redistributing the code in our repo, verify or reimplement the published
  formulas ourselves (they are all in the paper).
- In the UI/report, label the number as *"estimated immediate fatalities under
  the selected impact scenario"*, never as a NASA prediction.

### 2.3 Economic layer — the hard part

**No valid formula of the form `damage_usd = deaths * constant`.** Building
damage and human fatalities are two different consequences. A defensible
direct-loss model is:

```
L = sum_i sum_k  A_i,k * r_k(I_i)
```

where `A_i,k` is the replacement value of asset type `k` in cell `i` (from
GEM: `BLDG_REPL_COST_USD`, `COST_STRUCTURAL_USD`, `COST_NONSTRUCTURAL_USD`,
`COST_CONTENTS_USD`, ...), `I_i` is the physical intensity in that cell, and
`r_k(I_i)` is the loss ratio for asset type `k` at that intensity. This is the
same "loss ratio x asset cost" structure OpenQuake uses.

**No double counting**: a building already destroyed by wind cannot lose
another 100% to thermal radiation. How effects combine on the same asset must
be an explicit, documented rule (e.g. take the max ratio per asset, or a
documented product form).

Three implementation tiers:

| Tier | Approach | Caveat |
|---|---|---|
| A — educational proxy (proposed MVP) | Build intensity bands per effect and assign documented or openly assumed loss ratios per band | This is OUR model, labeled as such (`damage_method = 'educational_loss_proxy_v1'`), not "a GEM asteroid loss model" |
| B — per-hazard fragility | Real fragility/vulnerability curves for blast, wind, thermal, shaking | Needs a source per curve and an overlap rule; much more work |
| C — full loss framework | pelicun / OpenQuake where applicable | Frameworks do not choose our models for us |

**Rule**: if we cannot justify a loss ratio, the value stays `NULL` rather
than inventing a scientific-looking number.

GEM caveats: license is CC BY-NC-SA 4.0 (attribution, non-commercial,
share-alike — check compatibility with how we publish the repo); the
spatially-disaggregated data requires an access request; field coverage varies
per country and must be checked file by file. Fallback if GEM is not
obtainable in time: GeoNames population + a documented per-capita asset value
proxy, explicitly labeled.

## 3. Keeping simulated results comparable with EM-DAT

For historical rows (EM-DAT):

- `deaths` = `Total Deaths` (includes confirmed dead + missing presumed dead —
  not identical to "immediate fatalities"; document this).
- `damage_usd` = `Total Damage ('000 US$)` x 1000, or the inflation-adjusted
  variant — but then record the price base year.
- Empty EM-DAT cells are not confirmed zeros: keep `NULL`, never fill 0.

Scopes differ: our simulation would measure **direct building replacement
loss**; EM-DAT damage can cover a broader economic scope. Add provenance
columns so the game never presents the two as the same measure:

```text
damage_scope       -- e.g. 'direct_building_replacement'
currency_base_year
damage_method      -- e.g. 'educational_loss_proxy_v1'
```

## 4. Sentry inputs

Use mode O per asteroid:

| Field | Meaning |
|---|---|
| `diameter` | km |
| `mass` | kg (derived from diameter assuming density 2.6 g/cm3 — an estimate, document it) |
| `v_imp` | velocity at atmospheric entry, km/s — **use this one** |
| `ip` | impact probability (Earth, not any city) |

Pitfalls:

- Do not use `v_inf` (hyperbolic excess velocity) as if it were `v_imp`.
- Sentry provides **no impact coordinates**: the "asteroid x city" pairing is
  our game scenario, not a NASA prediction. The chosen city is an assumption.
- `impact_probability` must not be multiplied into our per-city death counts
  and presented as expected deaths at that city. Our game metric is:
  *"if asteroid a strikes city c, what are the estimated consequences?"*
  — a conditional, scenario-level quantity. Risk-weighted indices would need
  a spatial impact probability distribution we do not have.

## 5. Schema adjustments to discuss

Same asteroid x city can yield different results when assumptions change
(entry angle, density, model version, exposure snapshot). Proposals:

1. New `dim_scenario` table:

```text
dim_scenario
------------
scenario_key
impact_latitude
impact_longitude
entry_angle_deg
impactor_density_kgm3
target_type
physics_model_version
fatality_model_version
damage_model_version
exposure_version
assumptions_json
```

2. `fact_event_toll` gains `scenario_key` (NULL or a "not applicable" member
   for historical rows).
3. Move distance/location-dependent results (`max_wind_kmh`, `shaking_class`,
   ...) out of `dim_event`: in a simulation they are outputs at a specific
   location, not fixed asteroid attributes.

## 6. Proposed pipeline and checks

```text
Sentry + EM-DAT + exposure
        -> raw snapshots
        -> staging + unit conversion + quality checks
        -> scenario generation
        -> physics -> fatalities -> economic loss
        -> validated simulation results
        -> fact_event_toll / reporting views
        -> Streamlit game reads stored results (never computes live)
```

Validation checks:

- `0 <= deaths <= exposed_population`
- `0 <= damage_usd <= exposed_asset_value` (for direct replacement loss)
- NULL vs 0 never conflated
- Unit conversions explicit: km/s vs m/s, Pa, USD, km vs m
- Determinism: cache results per (input hash, model versions)
- City totals: state clearly whether a figure is the city proper or the
  affected region

## 7. MVP proposal (to confirm)

| Component | Choice |
|---|---|
| Scope | Fixed set of cities, land impacts; no tsunami, no global climate effects |
| Physics | `ImpactEffect==1.0.0` behind our adapter, validated against Purdue on a few scenarios |
| Deaths | Rumpf models (paper formulas; repo code pending license check) |
| Exposure | GEM if access + license work for us; else GeoNames + documented proxy |
| Damage USD | GEM asset value x tier-A loss ratios, labeled `educational_loss_proxy_v1` |
| Unknowns | stay NULL |
| Execution | Computed in the pipeline, game reads stored rows |

## 8. Open questions for the team

1. **Physics**: accept `ImpactEffect==1.0.0` after smoke tests, or reimplement
   the subset of Purdue formulas we need (avoids a dependency of unknown
   quality, costs time)?
2. **Deaths license**: reimplement Rumpf formulas from the paper ourselves
   (safe), or use the repo code (faster, license unclear)?
3. **>400 m asteroids**: extrapolate with a warning label, or clamp/skip?
4. **GEM access**: who requests the disaggregated data, and is CC BY-NC-SA
   4.0 acceptable for this repo? Fallback = GeoNames proxy?
5. **Loss ratios (tier A)**: which source values do we use for the bands, or
   do we agree on openly-stated assumptions? What is the effect-combination
   rule (max vs product)?
6. **Scenario defaults**: entry angle 45 deg, density from Sentry (2.6
   g/cm3) — good defaults, or do we vary them?
7. **Schema**: do we accept `dim_scenario` + moving location-dependent
   attributes out of `dim_event`, or keep the current star schema for the
   MVP and version via assumptions in a side table?
8. **Damage scope for the game label**: "estimated direct building damage" —
   agreed wording?

Once these are answered, this document is updated with the decisions and
becomes the reference for the implementation in the Airflow pipeline.
