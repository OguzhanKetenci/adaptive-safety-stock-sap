# Design decisions

Decisions made while building this project autonomously, with the reasoning behind each.
Grouped by topic; each line is a choice someone could reasonably have made differently.

## Data

| # | Decision | Why |
|---|----------|-----|
| D1 | Horizon of **540 days** (about 18 months), regime shift on day 180. | The brief asks for 365+ days. 18 months gives a full year after the shift and shows the yearly seasonality at least once. |
| D2 | **30 materials, one plant each** (18 in plant 1000, 12 in plant 2000). | Keeps MARC 1:1 with MARA, which makes the app easier to read. The code keys everything by MATNR + WERKS, so a material in two plants would work too. |
| D3 | Seeds are fixed integer tuples passed to `numpy.random.default_rng([42, material, stream])`. | Gives the same data on every machine. Python's `hash()` is never used, because it is salted per process. |
| D4 | Daily consumption is stored as an aggregated goods-issue table (`consumption_daily`, like MSEG 261/201). `MVER` is the monthly roll-up with `GSVBR` = total consumption. | In real SAP, MVER is monthly (GSV01..GSV13). Daily statistics need MSEG, so both tables are provided. |
| D5 | Actual lead time = `EKBE.BUDAT` (goods receipt, BWART 101) − `EKKO.BEDAT` (PO date). PO history starts 150 days before go-live. | This is how a planner would measure supplier lead time in SAP. The pre-history means lead-time statistics already exist on day 0. |
| D6 | Actual supplier lead times average 95–125% of the planned `PLIFZ` and are gamma distributed. | In practice PLIFZ is rarely maintained and suppliers tend to deliver late. This shows why lead times should be measured, not read from master data. |
| D7 | Simulated orders take their lead times from a separate, pre-drawn sequence per material, with the same distribution as the PO history. Every method uses the same sequence. | Common random numbers: the methods differ only in their logic, not their luck. Lead-time *statistics* still come from the EKKO/EKBE receipt history, which methods only see once the receipt has been posted. |
| D8 | Regime-shift materials start with low volatility (CV 0.15–0.35). On day 180 the mean moves ×1.6 or ×0.6 and the volatility ×2.2. | With a high starting CV, clipping demand at zero hid the volatility jump on the "down" materials. |
| D9 | Synthetic demand = consumption. | In real SAP, consumption under-reports demand during stockouts (censored demand). This is listed as a limitation. |

## Segmentation & service levels

| # | Decision | Why |
|---|----------|-----|
| S1 | ABC on consumption value (Pareto cut-offs: 80% / 95%). XYZ on the **daily** demand CV (X ≤ 0.5 < Y ≤ 1.0 < Z). | These are the common textbook cut-offs. Daily CV matches the daily simulation bucket. |
| S2 | Segmentation is computed once from the 60-day baseline. | No hindsight. Re-segmenting periodically is listed as a next step. |
| S3 | Target cycle service levels: AX 98%, AY 97%, AZ 95%, BX 96%, BY 95%, BZ 92%, CX 93%, CY 92%, CZ 90%. | Highest protection for high-value, predictable items; lowest for cheap, erratic ones. All values can be overridden in the app. |
| S4 | Intermittent = ADI > 1.32 (Syntetos–Boylan cut-off). | This is the standard demand-classification threshold. |

## Methods & simulation

| # | Decision | Why |
|---|----------|-----|
| M1 | **Static** = formula SS from days 0–59, written to MARC (EISBE, MINBE, BSTFE) and never changed. | This is the "set once" SAP practice the project challenges. |
| M2 | During the 60-day warm-up **all methods use the static settings**. Adaptive methods start recalculating on day 60. | Every method enters the KPI period in exactly the same state, which makes the comparison clean. |
| M3 | Adaptive recalculation every **7 days** by default, using a 90-day demand window and the receipts of the last 180 days (at least 3 receipts). | Weekly is a realistic background-job cadence. Window and frequency are sidebar parameters. |
| M4 | EWMA uses exponential weights (1 − α)^age with α = 0.05 for demand and α = 0.2 for lead times. Its mean and variance are both weighted. | Same effect as recursive EWMA, written in vectorised form (it is called thousands of times). |
| M5 | Empirical method: the service-level percentile of all observed lead-time-demand sums. Every observed lead time is combined with every start day in the last max(window, 180) days. ROP = that percentile, SS = ROP − expected LTD. | This bootstrap is deterministic and needs no normal assumption, which suits lumpy demand. It falls back to the formula when there are fewer than 10 samples. |
| M6 | **"Adaptive (recommended mix)"** = rolling window for regular items, empirical percentile for intermittent items. The choice is made from the baseline ADI, before any results are known. | The headline number must not come from picking the best method after the fact. EWMA does slightly better in this data set, but it was not chosen in advance, so it is reported but not used for the headline. |
| M7 | Q = ceil(d_mean × LT_mean), recalculated together with SS for adaptive methods, minimum 1 unit. | As specified. In SAP terms this corresponds to BSTFE. EOQ would be a natural extension. |
| M8 | When IP ≤ ROP, order n·Q so that IP rises above ROP again (an (s, nQ) policy). One order per day at most. | Prevents the policy from falling behind after a large demand spike. |
| M9 | Order of events each day: recalculate → receipts → demand → reorder check. | Parameters only ever use data from before today (a test checks there is no look-ahead). |
| M10 | Cycle service level = share of **receipt-to-receipt cycles** with no unmet demand. | My first version counted overlapping order windows, so one stockout was counted twice. |

## Costs

| # | Decision | Why |
|---|----------|-----|
| C1 | Holding cost 20% of unit value per year. Ordering cost €50 per PO. | Typical planning assumptions. |
| C2 | Stockout cost per unit = **50% of unit value** (a factor, not a flat € amount). | Prices range from about €2 to €1,000. A flat penalty per unit would make stockouts on cheap parts dominate and those on expensive parts look free. |
| C3 | In backorder mode each backordered unit is charged once. | Keeps lost-sales and backorder costs comparable. |

## SAP export & approval

| # | Decision | Why |
|---|----------|-----|
| E1 | Semicolon CSV, integer quantities, CHANGE_PCT with a decimal point. | Works for LSMW / MM17 flat-file uploads and Excel in a German locale. Integer quantities avoid decimal-separator problems. |
| E2 | Status logic: change under 5% → `NO_CHANGE` (dead band); up to ±30% → `AUTO_UPDATE`; above ±30% → `NEEDS_PLANNER_APPROVAL`. | The dead band stops the master data from changing back and forth every week. The ±30% gate keeps a human in charge of big moves. |
| E3 | The status takes the **larger of the EISBE and MINBE changes**. | With DISMM = VB, MRP is triggered by the reorder point MINBE. A big MINBE move should not be auto-posted just because EISBE barely changed. |
| E4 | Two files: the full proposal list for planners (with reason and MRP controller DISPO), and an MM17 upload file with only the AUTO_UPDATE rows (MATNR;WERKS;EISBE;MINBE). | This separates "inform" from "post". |
| E5 | The proposal shown is what the job would propose at the end of the horizon, compared with today's MARC values. | This is the first run after 16 months of static settings, so most items need approval. In normal weekly operation the changes would be small and incremental. |

## Tooling

| # | Decision | Why |
|---|----------|-----|
| T1 | Added `pyproject.toml` with only a pytest `pythonpath` setting. | Lets the tests import `src/adaptive_ss` without installing the package. No new dependencies. |
| T2 | No `gh` CLI on the machine. Pushes go through plain `git` with the existing credential manager. | — |
