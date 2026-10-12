# Adaptive safety stock in SAP: integration briefing

*From: Supply Chain (planning) · To: SAP MM/PP development · Level: design, no code*

This note describes how the logic in this repository would run inside a real SAP ECC or S/4HANA
system. I describe **what** the job must do and **why**. The ABAP design, transport route and
authorisation concept are for the development team to decide.

---

## 1. Business goal in one paragraph

Safety stock (`MARC-EISBE`) and, for reorder-point materials, the reorder point (`MARC-MINBE`) are
maintained once and then go stale. We want a **weekly background job** that recalculates both from
recent consumption and actual supplier lead times. It should post small, routine corrections
automatically and send large changes to the responsible MRP controller for approval. Planners stay
in control. The job takes over the arithmetic, not the decision.

## 2. Scope

| In scope | Out of scope (for now) |
|---|---|
| MRP types **VB** (manual reorder point) and **PD** (MRP with safety stock) | VM/V1/V2 (SAP calculates the reorder point itself from its forecast) |
| Plant-level materials (MARC) with consumption history | Storage-location MRP, MRP areas (MDMA) |
| External procurement (BESKZ = F) | In-house production lead times (would use AFKO/AFRU instead of EKBE) |
| One plant at a time; selection by plant, MRP controller, material type | Multi-echelon / stock transport orders |

## 3. Data to read

### 3.1 Demand: consumption history

| Source | Fields | Notes |
|---|---|---|
| **MSEG** (ECC) / **MATDOC** (S/4) | MATNR, WERKS, BWART, MENGE, SHKZG, BUDAT_MKPF | Daily buckets. Movement types to count as consumption: **261** (GI for order), **201** (GI to cost centre), **601** (delivery), and their reversals **262/202/602** (netted). Exclude transfer postings (311, 301) and scrapping (551). |
| **MVER** | GSV01…GSV13 (total), MGV01…MGV13 (unplanned) | Monthly. Good enough as a fallback or for a fast first version, but too coarse to estimate daily volatility. |

**Look-back window:** 90 days for the rolling method, 180 days for intermittent materials. This
should be a parameter per plant.

**Important pitfall: censored demand.** When the material was out of stock, consumption was lower
than demand. Where possible, add back open/unfulfilled requirements from that period (e.g. backlog
from `VBBE`, missing parts from `RESB` with `BDMNG > ENMNG`). Otherwise the job will "learn" that a
material needs less stock exactly because it ran out.

### 3.2 Lead time: purchasing history

| Source | Fields | Notes |
|---|---|---|
| **EKKO** | EBELN, BEDAT, LIFNR, BSART | PO creation date = start of lead time. Standard POs only (e.g. BSART NB). |
| **EKPO** | EBELN, EBELP, MATNR, WERKS, LOEKZ | Ignore deleted items (LOEKZ ≠ space). |
| **EKBE** | EBELN, EBELP, VGABE = 1, BWART 101, BUDAT | First goods receipt per item = end of lead time. Use only receipts where the PO was **not** changed long after creation (otherwise the lead time is unrealistically long). |
| EKET (optional) | EINDT | Requested delivery date. Useful later for supplier reliability KPIs (on-time %). |

Lead time = `EKBE-BUDAT` (first GR) − `EKKO-BEDAT`, in **working days** of the plant's factory
calendar (`T001W-FABKL`), to match how PLIFZ is interpreted. Take the receipts of the last 180 days,
with at least 3 observations. If there are fewer, fall back to the last 5 receipts, and if there
are none, to `MARC-PLIFZ` with zero variance.

### 3.3 Master data

| Table | Fields | Use |
|---|---|---|
| MARC | EISBE, MINBE, BSTFE, PLIFZ, WEBAZ, DISMM, DISPO, MMSTA | Current values; DISPO routes the approval; skip materials with a blocking plant status (MMSTA) |
| MBEW | VERPR / STPRS, PEINH | Unit value for ABC classification and the inventory value KPI |
| MARA | MEINS, MTART | Unit; selection by material type |

## 4. Calculation (per material/plant, weekly)

1. **Segment.** ABC by 12-month consumption value (80/95% Pareto cut-offs). XYZ by the coefficient
   of variation of daily demand (X ≤ 0.5, Y ≤ 1.0, Z > 1.0). Store the segment in a custom table and,
   if wanted, also in a free MARC field or as a classification characteristic.
2. **Target service level** from the segment matrix (e.g. AX 98% … CZ 90%). The matrix is a
   customising table maintained by supply chain, not hard-coded.
3. **Method.** If the average inter-demand interval is > 1.32 days, the demand is intermittent and
   the job uses the empirical percentile method. Otherwise it uses the formula
   `SS = z · √(LT_mean · σ_d² + d_mean² · σ_LT²)`.
4. **Reorder point** (VB only): `MINBE = d_mean · LT_mean + SS`.
5. **Round** up to whole units, or to the rounding value / pack size.

All parameters (window, review cycle, dead band, approval limit) live in a customising table per
plant. Planning should be able to change them without a transport.

## 5. Posting the result: the approval workflow

```
weekly job ──► proposal table (Z-table, one row per MATNR/WERKS/run)
                 │
                 ├─ |Δ| <  5 %          → NO_CHANGE   (logged only)
                 ├─ |Δ| ≤ 30 %          → AUTO_UPDATE → mass change of MARC-EISBE / MINBE
                 └─ |Δ| > 30 % or new   → NEEDS_PLANNER_APPROVAL
                                            │
                                 MRP controller (MARC-DISPO) work list
                                 approve / reject / override value + comment
                                            │
                                 approved rows → same mass change
```

* **Δ is the larger of the EISBE and MINBE changes.** With MRP type VB, the reorder point
  triggers procurement, so a large MINBE move must not slip through automatically.
* **Dead band (5%)** keeps the master data stable. Without it, EISBE would flicker every week and
  MRP would generate noise in MD06/MD07.
* **Approval limit (±30%)** keeps a human in the loop for big moves. Typical causes are a new
  customer, a phase-out, a supplier problem, or a data error such as a one-off bulk issue. The
  proposal carries a **reason text** (e.g. *"demand mean +93%, demand variability +86% vs. current
  setting"*) so the planner can decide in seconds.
* **Planner overrides** are kept. If a planner rejects a proposal or sets a manual value, that
  material gets a "frozen until" date and the job skips it until then.
* **Audit trail:** every posted change shows up in the material change documents (CDHDR/CDPOS, object
  MATERIAL), which is visible in MM04. The proposal table keeps old and new values, run ID, user
  and decision.

### Posting mechanism options (for the developer to choose)

| Option | Comment |
|---|---|
| **MM17** mass maintenance with a file upload | Simplest. Matches the CSV produced by this prototype (`MATNR;WERKS;EISBE;MINBE`). Good for a pilot. |
| **LSMW** recording / BAPI | Same file layout; useful in ECC if MM17 is restricted. |
| **BAPI_MATERIAL_SAVEDATA** (PLANTDATA-SAFETY_STK, REORDER_PT) called from the job | Fully automatic. Recommended for production once the pilot is accepted. |
| S/4HANA: Fiori *Mass Maintenance of Products* / API_PRODUCT_SRV | Equivalent in S/4. |

The job should run with a dedicated **technical user**, and change documents should show that
user. The approval UI can be a simple ALV report with approve/reject buttons, or a Fiori list. A
Business Workflow is optional; an e-mail notification to the MRP controller is usually enough.

## 6. Scheduling

| Step | When | Transaction / tool |
|---|---|---|
| Recalculation job | Weekly, Sunday night, before the MRP run | SM36 job, report variant per plant |
| Approval work list | Monday morning | custom report or Fiori app for MRP controllers |
| Posting of approved changes | Daily, after approvals | same job, step 2 |
| MRP run | Nightly as today | MD01 / MD01N |

Run the recalculation **before** MRP, so that the new reorder points are already used in the same
night's planning run.

## 7. Monitoring: how planners see the effect

* **MD04 (stock/requirements list):** the safety stock line shows the new EISBE. For VB materials
  the reorder point is visible in the header. Planners use MD04 to sanity-check a proposal before
  they approve it.
* **MD07 (collective stock/requirements list):** filter by MRP controller and look at the traffic
  lights (days of supply / receipt days of supply). After the go-live, there should be fewer red
  lights on growing items and fewer "excess stock" items on declining ones.
* **MD06 / exception messages:** watch exception groups for "safety stock undershot" and
  "reorder point undershot". Their frequency is a direct KPI for this project.
* **KPIs to report monthly** (by segment): fill rate / backorder lines, stockout days, average
  inventory value, number of EISBE changes (auto vs. approved vs. rejected), and the share of
  proposals rejected by planners. A high rejection rate means the parameters need tuning.

## 8. Rollout suggestion

1. **Shadow mode (4–8 weeks):** run the job, write proposals, post nothing. Compare the proposals
   with what planners would have done, and tune the dead band, approval limit and windows.
2. **Pilot:** one plant, one MRP controller, B and C items only (low risk), auto-update enabled.
3. **Extend** to A items with the approval step, then to further plants.
4. **Review** the segment matrix twice a year with sales and finance. The service-level targets are
   a business decision, not an IT one.

## 9. Open questions for the development team

* Where should the proposal table and the customising tables live? (Z-tables vs. BRF+ for the
  rules.)
* Can consumption be read efficiently from MATDOC for 12 months × all materials of a plant, or do we
  need a pre-aggregated table?
* Is BAPI_MATERIAL_SAVEDATA allowed for a background user, or does governance require MM17 with a
  named user?
* How do we handle materials with planning-relevant changes already pending in change requests (MDG)?
