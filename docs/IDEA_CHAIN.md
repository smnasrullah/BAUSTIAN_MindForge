# Idea Development Framework (hackathon guideline §10)

Problem statement: For MFS agents and their distributors, unplanned cash or e-money stockouts cause turned-away transactions and costly emergency van trips. We will build AgentPulse AI that uses hourly transaction history, calendar events and weather to forecast dual-float demand and recommend rebalancing or nearby agent-to-agent swaps with human approval, with success measured by stockout hours reduced, transaction value saved and van trips avoided versus a fixed-threshold alert baseline.

| Step | Answer |
|---|---|
| 1 User | MFS agent (primary); distributor / field-ops officer (secondary) |
| 2 Problem | Agent runs out of cash or e-money, customer is turned away. Today: reactive, fixed-threshold alerts, van trips |
| 2b Problem evidence | Public numbers (IMF/FRED, Bangladesh Bank via press), sourced replenishment description, stockout incidence calibrated at 0.32 / 1.03 / 2.99% of agent-hours (stress test, models not retrained), opportunity sizing illustration. Field interviews: planned, 0 done. See docs/PROBLEM_EVIDENCE.md, docs/INCIDENCE_SENSITIVITY.md |
| 3 Why now | Digital transaction logs exist; quantile ML is cheap on CPU; LLMs make Bangla guidance and voice accessible |
| 4 Solution | Agent app (forecast, countdown, what-if, copilot) + distributor map dashboard (risk, swaps, anomalies, impact) |
| 5 AI role | LightGBM quantile forecast; scipy optimisation for swaps; Isolation Forest for agent risk; SHAP for reasons; LLM + RAG for Bangla/English explanations, copilot and briefings (language only) |
| 6 Impact | Stockout hours, transaction value saved (BDT), van trips avoided, vs a fixed-threshold alert (float < 20% of capacity). Backtest, 14 held-out days, 300 synthetic agents (docs/METHODS.md §3): stockout hours 322 -> 76 (-76%); 2.05 M BDT of transactions no longer turned away (32.5 k BDT cash-out fees); van trips 786 -> 1,065 (+279: none avoided at the 20% rule). At the AI's van budget the rule would have ~207 stockout hours; no threshold up to 50% reaches 76 (50%: 104 h with 4,030 trips). Targets per 300 agents per 14 days: stockout hours -70% or better (met: -76%); value saved >= 2.0 M BDT (met: 2.05 M); at equal van budget >= 100 fewer stockout hours than the rule (met: 131); van trips <= the 20% rule's 786 (not met: 1,065; next step: feed routine refills to the recommendation) |
| 7 Data | Fully synthetic, fixed seed, documented patterns (docs/SYNTHETIC_ASSUMPTIONS.md); last 14 days held out |
| 8 Validation | Pinball loss + MAE vs same-hour-last-week; stockout recall; anomaly precision/recall; fairness by group; walkthrough demo |
| 9 Scale | Same API contract can ingest upay data via adapter; shadow mode; governed anonymised data; retrain + drift monitoring; human approval retained |

Guideline "good project test": What happened? (stockout predicted for 3:40 PM) Why risky? (salary day, 2.3x cash-out) What should upay do next? (swap with nearby agent, distributor approves).
