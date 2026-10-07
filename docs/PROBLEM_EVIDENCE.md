# Problem evidence

Status: **no field interviews yet** (data/field/interviews.csv has 0 rows). Public figures below are
from the sources named; every other number is from our synthetic simulation or marked "unknown, to
be validated". Bangla summary of §1-3: [PROBLEM_EVIDENCE_BN.md](PROBLEM_EVIDENCE_BN.md).

## 1. The problem in public numbers

| Figure | Year | Source | Caveat |
|---|---|---|---|
| 1,828,870 registered mobile-banking agent outlets in Bangladesh (1,724,515 in 2023; 1,554,637 in 2022) | 2024 (2023, 2022) | IMF Financial Access Survey via FRED, series BGDFCMORNUM | "Registered", not "active" |
| About 1.44 million active MFS agents | Aug 2025 | Daily Sun, 1 Nov 2025 (daily-sun.com/5/837216), citing Bangladesh Bank | "Active" vs "registered" definitions differ, so it is not a decline from 2024 |
| 1.57 million agents | Jan 2023 | Financial Express, "Daily transaction of MFS crosses Tk 32b" | Press report |
| 652,101,737 MFS transactions worth Tk 1,567,877.4 million | Nov 2024 | Daily Star, Better Banking Together, citing Bangladesh Bank | Supplement; monthly figure |
| About 60% of MFS transactions were deposit and withdrawal, 40% digital payment | Jan 2023 | Financial Express (same article) | Share of transaction count; may have shifted since |

What these numbers do not say: how often agents run out of cash or e-money. No source in our list measures stockout incidence in Bangladesh. Mondato ("How best to keep afloat", blog.mondato.com/liquidity) reports that agents across three surveyed countries (not Bangladesh-specific) cited inability to predict demand as a significant factor in float management.

## 2. How replenishment works

**Sourced.** MicroSave/Helix survey of 2,800 agents in Bangladesh (undated in the source, appears mid-2010s; verify the year before citing): most agents have cash and e-float delivered to the outlet by a runner employed by a distributor or aggregator; median 12 cash deposits and 10 withdrawals per month in Bangladesh versus 4 and 3 in Kenya (microsave.net/?p=9676, nextbillion.net/take-that-telecoms). MicroSave, "Liquidity: solving agents' perennial problem": in Bangladesh and Pakistan liquidity is usually delivered by runners; float-level alerts and inter-agent transfers are discussed as ideas. Who pays the runner, and how long a delivery takes today at upay: unknown, to be validated.

**Channels in OUR simulation (all ASSUMPTION, synthetic, not upay figures).** Config in [backend/app/core/config.py](../backend/app/core/config.py) and the rule dataclasses; `.env` overridable.

| Channel | Who bears the cost (as modelled) | Delay | Config name | Value in code |
|---|---|---|---|---|
| Routine refill (bank run urban Sun-Thu 10:00; peri-urban Sun/Tue/Thu 11:00; rural distributor van 2x/week 11:00) | Not costed; identical in every scenario | none (float reset at that hour) | `TARGETS`, `refill_policy` in ml/data_gen/agents.py | targets e.g. rural 75% cash / 40% e-money of capacity |
| Ad-hoc top-up by the agent | Not costed | within the hour | `ADHOC_LOW_SHARE`, `ADHOC_PROB` (ml/data_gen/simulate.py:18-19) | below 8% of capacity, 12% chance per hour, 08-20 |
| Baseline dedicated van | 1,500 BDT per trip; payer not stated in code | 3 h | `VAN_COST_PER_TRIP_BDT`; `ImpactConfig.emergency_eta_h` | 1,500; 3.0 h |
| Batched van route (AI) | 1,500 BDT per trip split evenly over the cluster | 4 h | `VAN_LEAD_TIME_H`, `VAN_COST_PER_TRIP_BDT`, `VAN_CLUSTER_RADIUS_KM`, `VAN_MIN_BATCH_AMOUNT_BDT` | 4.0 h; 1,500; 10 km; 100,000 BDT |
| Urgent manual delivery | 2,500 BDT per delivery | 3 h | `URGENT_MANUAL_COST_BDT`, `emergency_eta_h` | 2,500; 3.0 h |
| Digital e-money top-up | fee on the amount; payer not stated in code | 15 min | `TOPUP_FEE_PCT`, `TOPUP_ETA_H` | 0.5%; 0.25 h |
| Self-fetch from distributor point | travel cost, borne by the agent as modelled | distance / speed | `SELF_FETCH_MAX_KM`, `SELF_FETCH_SPEED_KMH`, `TRAVEL_COST_PER_KM_BDT` | 10 km; 15 km/h; 10 BDT/km |
| Agent-to-agent swap | travel cost of hand-over | distance / speed | `SWAP_RADIUS_KM`, `SWAP_MIN_AMOUNT_BDT` | 5 km; 5,000 BDT |

**Sensitivity on the delay assumption.** The repo already contains a delivery-realism stress (docs/METHODS.md, `impact_realism.py`): physical deliveries fail 10% (arrive empty) or land 2 h late 25%. With it, stockout hours are 443 baseline / 99-104 AI instead of 322 / about 75 (docs/ML_UPGRADE_RESULTS.md:43; two model variants), so the relative reduction stays about 77-78% while absolute hours rise. Not re-run here. The van lead time (3-4 h) is the assumption that most drives the result; real lead time is unknown, to be validated in interviews (Q2).

## 3. Incidence: where ours comes from

- Generator (docs/SYNTHETIC_ASSUMPTIONS.md §4): agents refill on a fixed weekly routine to a target share of capacity, plus an ad-hoc top-up when a float falls below 8% (12%/h). Demand the float cannot cover is turned away. The generator's own note: about 3% of business hours have turned-away demand in the logged history under routine refills only (no AI, no alerts).
- Measured in the 14-day impact backtest (300 agents, 100,800 agent-hours, seed 42, docs/METHODS.md §3): baseline alert policy 322 stockout hours = **0.319%** of agent-hours (0.59% of business hours); AI-assisted policy 76 hours stored (75 in our rerun) = **0.074%**; no action 4,484 hours = 4.4%.
- Why the headline % needs incidence: "-76% stockout hours" is a ratio against a baseline that already prevents most stockouts. 247 hours avoided over 14 days is a small absolute number at 0.3% incidence. See [INCIDENCE_SENSITIVITY.md](INCIDENCE_SENSITIVITY.md): at 1.03% and 2.99% baseline incidence (stress test, same models) the reduction stays 79% and 77% but hours avoided become 823 and 2,312.
- Limits: incidence comes from our generator parameters, not from data. Real incidence is unknown, to be validated. The three levels are stress settings, not real-world rates.

## 4. Opportunity sizing (illustration, not a forecast)

Formula (script: [scripts/perf/opportunity_sizing.py](../scripts/perf/opportunity_sizing.py), reads backend/data/evidence/incidence_sensitivity.json):
- stockout hours per year = agents x 8,760 x incidence
- BDT per stockout hour = baseline value turned away / baseline stockout hours, measured per level (8,737 / 7,255 / 6,318 BDT; cash-out fee 138 / 119 / 103 BDT at `IMPACT_CASHOUT_FEE_PCT` 1.85%)
- worth of a 1% cut in stockout hours = 0.01 x hours per year x BDT per hour
- Values are customer transaction value turned away and the cash-out fee, **not** agent or provider revenue (split unknown, to be validated). Annualising a 14-day synthetic window assumes the same incidence all year, which is unproven.

Worth of a **1% cut in stockout hours**, BDT million per year (transaction value / cash-out fee):

| Population (agents, source) | Incidence 0.32% | Incidence 1.03% | Incidence 2.99% |
|---|---|---|---|
| Per 10,000 agents | 24.4 / 0.39 | 65.7 / 1.08 | 165.2 / 2.68 |
| 1,828,870 registered outlets, 2024 (IMF FAS via FRED) | 4,465 / 70.8 | 12,019 / 196.7 | 30,216 / 490.5 |
| 1,724,515 registered outlets, 2023 (IMF FAS via FRED) | 4,210 / 66.7 | 11,333 / 185.5 | 28,492 / 462.5 |
| About 1.44 million active agents, Aug 2025 (Daily Sun) | 3,516 / 55.7 | 9,463 / 154.9 | 23,791 / 386.2 |
| About 1.57 million agents, Jan 2023 (Financial Express) | 3,833 / 60.7 | 10,318 / 168.9 | 25,939 / 421.1 |
| upay agents | not in our sources | not in our sources | not in our sources |

Worth of the **measured cut** (about 77-79%) per 10,000 agents: 1,783 / 4,856 / 11,571 BDT million per year of transaction value. Mind the scale: these are upper-bound style illustrations on a synthetic world; no claim that upay or the market loses this much. Add an upay figure with `python scripts/perf/opportunity_sizing.py --upay N` once known.

## 5. Validation status

Field interviews: **planned, 0 done** (rows in data/field/interviews.csv: 0). Template: data/field/interviews.template.csv. Nothing in the app claims field evidence; the Discovery page labels its hypotheses SIMULATED.

**Interview guide / সাক্ষাৎকার নির্দেশিকা** (7 questions; verbal consent first)

| # | English | বাংলা |
|---|---|---|
| 1 | How often do you run out of cash or e-money in a month? Which is more common? | মাসে কতবার আপনার ক্যাশ বা ই-মানি শেষ হয়ে যায়? কোনটা বেশি হয়? |
| 2 | What do you do then? How long does it take, what does it cost, and who do you get it from? | তখন আপনি কী করেন? কত সময় লাগে, কত খরচ হয়, আর কার কাছ থেকে নেন? |
| 3 | Which days and times are the worst? | কোন কোন দিন ও সময়ে সবচেয়ে বেশি সমস্যা হয়? |
| 4 | When a customer leaves because you have no cash or e-money, what do you lose? | ক্যাশ বা ই-মানি না থাকায় গ্রাহক ফিরে গেলে আপনার কী ক্ষতি হয়? |
| 5 | Do you ever have too much cash or e-money? What is the problem then? | কখনো কি আপনার কাছে বেশি ক্যাশ বা ই-মানি জমে যায়? তখন কী সমস্যা হয়? |
| 6 | Would you swap float with a nearby agent? On what conditions, any trust worries? | আশেপাশের এজেন্টের সাথে ক্যাশ/ই-মানি বদলাবদলি করতে রাজি হবেন কি? কী শর্তে, বিশ্বাস নিয়ে কোনো চিন্তা আছে? |
| 7 | Distributors: how many agents do you serve, how do runners or vans work, how do you handle emergencies? | ডিস্ট্রিবিউটর: কতজন এজেন্টকে সেবা দেন, রানার বা ভ্যান কীভাবে চলে, জরুরি অবস্থা কীভাবে সামলান? |

**Consent and privacy.** Verbal consent before starting; say it is optional and can stop any time. Record no names, no phone numbers, no shop identification; use only the id, area type (urban/rural) and role. Store answers only in data/field/interviews.csv; do not photograph shops.

## 6. Sources to verify by a human
Years and wording of every source above; the Helix survey year (appears mid-2010s); registered vs active definitions; upay's own agent count (not in our sources); who pays for runners and van trips.
