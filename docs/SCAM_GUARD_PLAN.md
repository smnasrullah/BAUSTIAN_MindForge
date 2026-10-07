# AgentPulse: Scam-aware Cash-out Guard (F13) — পূর্ণ পরিকল্পনা ও প্রম্পট

এই ফাইলে আছে: কাজের ক্রম, আগের সমস্যাগুলো পরে ঠিক করলে কোনো সমস্যা হবে কিনা, ফিচারটার পূর্ণ ডিজাইন, প্রজেক্টে কী কী নতুন যোগ হবে (tree), CLAUDE.md-তে কী বদলাবে, আর কপি করে দেওয়ার মতো প্রম্পট (কোন মডেলে দিতে হবে সহ)।

> নোট: প্রজেক্ট ফোল্ডারে হ্যাকাথনের PDF পাইনি। তাই track-এর তথ্য নিয়েছি তোমার লেখা থেকে ("Track 1: scam intelligence, real-time risk scoring") আর `docs/IDEA_CHAIN.md` ও `docs/JUDGING_MAP.md` থেকে। PDF-এ Track 1 নিয়ে আর কোনো শর্ত থাকলে (যেমন নির্দিষ্ট metric বা ডেটা) S0 প্রম্পট দেওয়ার আগে `docs/` ফোল্ডারে `HACKATHON_BRIEF.md` নামে লিখে রাখো। S0 প্রম্পট সেই ফাইলটা পড়বে।

---

## ১. এক নজরে: কী করবে, কোন ক্রমে

| ধাপ | কী | মডেল | কে করবে |
|---|---|---|---|
| 0 | **এখনই commit করো** (Prompt 1 আর 2-এর কাজ) | — | তুমি নিজে |
| S0 | প্রস্তুতি: spec ফাইল, CLAUDE.md, test-এর সময়সীমা | **Opus 5.5, Medium** | Claude |
| S1 | সিন্থেটিক ওয়ালেট লেজার + স্ক্যাম প্যাটার্ন + ML মডেল | **Opus 5.5, High** | Claude |
| S2 | Backend: rules, scoring API, audit, LLM wording, distributor/admin API | **Opus 5.5, Medium** (অথবা Sonnet 5.5, High) | Claude |
| S3 | Frontend (agent কাউন্টার স্ক্রিন, distributor watch, admin), e2e, docs | **Sonnet 5.5, High** | Claude |
| — | তারপর Prompt 1 ও 2-এর বাকি সমস্যা (FIX প্রম্পট, নিচে আছে) | Opus 5.5, Medium | Claude |
| — | তারপর Prompt 3 (Copilot), নিচের ছোট সংযোজন সহ | Opus 5.5, Medium | Claude |

নিয়ম (প্রতিটা প্রম্পটের আগে):
1. `/clear` দাও। নতুন সেশনে আগের কথা থাকে না, তাই token কম লাগে।
2. Docker Desktop চালু রাখো, অন্য Claude Code সেশন বন্ধ রাখো।
3. মাঝপথে model বা effort বদলিও না।
4. প্রতিটা প্রম্পট শেষ হলে রিপোর্ট পড়ো। ঠিক লাগলে **নিজে commit করো**, তারপর পরের প্রম্পট দাও।

### ধাপ 0 কেন সবচেয়ে জরুরি
এখন তোমার working tree-তে Prompt 1 আর 2-এর ~১০০ ফাইলের বদল **commit ছাড়া** পড়ে আছে। এর উপর নতুন ফিচার বসালে তিনটা বিপদ:
- কোনো কিছু ভাঙলে কোনটা নতুন ফিচারের দোষ আর কোনটা পুরনো, আলাদা করা যাবে না।
- ফিরে যাওয়ার কোনো পথ থাকবে না (প্রম্পটগুলো নিজে commit করে না)।
- পরে "FIX" প্রম্পট কোন বদলটা ঠিক করছে, সেটা diff দেখে বোঝা যাবে না।

```powershell
cd D:\Git\AI_Hackathon_DIU
git add -A
git status --short    # .env তালিকায় থাকলে থামো (.gitignore-এ থাকার কথা)
git commit -m "live clock + ML upgrade (uncommitted work from prompts 1-2)"
git switch -c feature/scam-guard
```

---

## ২. আগের সমস্যাগুলো পরে ঠিক করলে কোনো সমস্যা হবে?

**সংক্ষেপে: না, পরে করা নিরাপদ। শুধু দুটো ব্যাপার আগে সামলাতে হবে, আর দুটো ফিচার-ডিজাইনে মাথায় রাখতে হবে।** তিনটাই নিচের প্রম্পটে ঢোকানো আছে।

| আগের সমস্যা | নতুন ফিচারের সাথে সম্পর্ক | সিদ্ধান্ত |
|---|---|---|
| ML-3: fast pytest ২১৫–৩৫২ সেকেন্ড, সীমা ২৪০ সেকেন্ড, দুবার timeout | নতুন test যোগ হলে **প্রতিটা check timeout হবে**, Claude বারবার ব্যর্থ হবে আর token নষ্ট হবে | **আগে করতে হবে।** S0-এ সীমা configurable হবে (ডিফল্ট ৪২০ সেকেন্ড)। test দুর্বল করা হবে না |
| ML-2 / Clock-2: hourly tick ৫০.২ সেকেন্ড (বাজেট ৬০), মাঝরাতে ৯০–১০০ সেকেন্ড | স্ক্যাম scoring tick-এ ঢোকালে বাজেট ছাড়িয়ে যাবে | ডিজাইনে সামলানো: scoring হয় **অনুরোধের সময়** (on-demand)। tick-এ শুধু নতুন ঘণ্টার লেজার ডেটা তৈরি হয় (সীমা ≤ ২ সেকেন্ড, মাপা হবে) |
| Clock: fixed mode-এ ডেটা bit-identical; ML-1: anomaly recall ০.৫৩, gate প্রায় ছুঁয়ে পাস | নতুন generator যদি পুরনো random stream থেকে সংখ্যা নেয়, **পুরনো সব ডেটা বদলে যাবে**। তখন anomaly gate ফেল করতে পারে আর benchmark নষ্ট হবে | ডিজাইনে সামলানো: লেজারের জন্য **আলাদা RNG stream** (seed থেকে derive করা)। পুরনো টেবিলে হাত দেওয়া হবে না। আগের মতো fingerprint test দিয়ে প্রমাণ করা হবে |
| Clock-1 / ML-12: main stack এখনো পুরনো image-এ চলছে | নতুন migration 0024 আসবে 0023-এর পরে। চেইন সোজা থাকলে কোনো সমস্যা নেই | কিছু করার নেই। প্রম্পটে "migration chain linear" চেক রাখা আছে |
| ML: anomaly features, conformal bands, joint stockout, helper model, drift, replay | আলাদা মডিউল, স্ক্যাম গার্ড এগুলো ছোঁয় না | পরে ঠিক করলে কোনো সমস্যা নেই |
| Clock-3: replay ≠ live সংখ্যা | Prompt 3 replay-র key বদলাবে | Prompt 3-এ এমনিতেই ঠিক হবে |

ক্রম তাহলে: **commit → S0 → S1 → S2 → S3 → commit → FIX প্রম্পট → commit → Prompt 3।**
FIX প্রম্পট স্ক্যাম গার্ডের পরে দিলে সুবিধা: FIX-এর test run স্ক্যাম গার্ডের test-ও চালাবে, তাই tick বা anomaly ঠিক করতে গিয়ে নতুন ফিচার ভেঙে গেলে সাথে সাথে ধরা পড়বে।

---

## ৩. ফিচার ডিজাইন (F13: Scam-aware Cash-out Guard)

### সমস্যা আর গল্প
কেউ ফোনে ঠকিয়ে বা "ভুল নম্বরে টাকা গেছে" বলে অনেক মানুষের কাছ থেকে টাকা একটা ওয়ালেটে আনায় (mule account)। সেই টাকা সবচেয়ে দ্রুত cash-out করে **এজেন্টের কাউন্টার থেকে**। এজেন্টই শেষ প্রতিরক্ষা। আবার ঠিক এই cash-out-গুলোই এজেন্টের ক্যাশ হঠাৎ শেষ করে দেয়। তাই **ক্যাশ ঘাটতি আর ঠকবাজি একই এজেন্টের সমস্যা**। এটাই Track 05 (liquidity) আর Track 1 (scam)-এর মধ্যে সেতু।

Judge-এর জন্য "good project test":
- **কী হলো:** ০১৭••••৪৫২ নম্বর থেকে ৪৮,০০০ টাকা cash-out চাওয়া হয়েছে।
- **কেন ঝুঁকি:** আজ ৮ জন আলাদা মানুষ এই নম্বরে টাকা পাঠিয়েছে, শেষ টাকা এসেছে ১২ মিনিট আগে, নম্বরটা আজ আরও ৩টা এজেন্টে cash-out করেছে।
- **এরপর কী:** NID দেখো, "কে পাঠিয়েছে?" জিজ্ঞেস করো, সন্দেহ থাকলে official support-এ জানাও। সিদ্ধান্ত এজেন্টের, আর সেটা audit log-এ যায়।

### কাজের ধারা (counter flow)
1. এজেন্ট `/agent/scam-check` স্ক্রিনে গ্রাহকের ওয়ালেট নম্বর আর টাকার অঙ্ক লেখে (demo mode-এ নমুনা নম্বরের chip থাকে)।
2. Backend ২০০ ms-এর মধ্যে উত্তর দেয়: ঝুঁকির স্তর (low / verify / high-risk), probability, ৩টা পর্যন্ত কারণ, প্রতিটার সাথে সংখ্যা ("৮ জন পাঠিয়েছে"), করণীয় ধাপ, বাংলা/ইংরেজি সতর্কবার্তা, model_version, generated_at।
3. এজেন্ট সিদ্ধান্ত দেয়: চালিয়ে গেছি / যাচাই করে চালিয়েছি / ফিরিয়ে দিয়েছি / রিপোর্ট করেছি, ইচ্ছা হলে নোট সহ। এটা audit_log-এ যায়।
4. Distributor `/distributor/scam-watch`-এ দেখে: তার এজেন্টদের কাছে আজকের high-risk চেক, একাধিক এজেন্টে ঘোরা নম্বর (masked), ফিরিয়ে দেওয়া টাকার পরিমাণ, আর এর ফলে ক্যাশ কতটা বাঁচল (liquidity link)।
5. Admin `/admin/models`-এ স্ক্যাম মডেলের model card দেখে (metrics, fairness, threshold)।

### সিস্টেম কখনো যা করবে না (hard rules)
- **লেনদেন আটকাবে না।** শুধু পরামর্শ দেবে, সিদ্ধান্ত সবসময় এজেন্টের।
- গ্রাহককে "প্রতারক" বলবে না। শব্দ হবে "যাচাই করুন" বা "সতর্ক থাকুন"।
- কারা টাকা পাঠিয়েছে (sender identity), সেটা কোনো এজেন্ট দেখবে না। দেখবে শুধু গোনা সংখ্যা (aggregate)।
- ওয়ালেট নম্বর DB-তে plain অবস্থায় থাকবে না। থাকবে HMAC hash আর শেষ ৩ অঙ্ক।
- LLM কোনো score বা সিদ্ধান্ত দেবে না। শুধু বাক্যটা সুন্দর করবে (template fallback সহ, numbers guard দিয়ে)।
- লিঙ্গ, বয়স, ধর্মের মতো কোনো demographic feature ব্যবহার হবে না। ভুল-সতর্কতার হার (false positive) জেলা ও শহর/গ্রাম ধরে মাপা হবে।
- নম্বর খুঁজে খুঁজে দেখা (enumeration) আটকাতে প্রতি এজেন্টের জন্য rate limit থাকবে। প্রতিটা চেক log হবে।

### ML পদ্ধতি (judge-এর কাছে "AI depth")
- **ডেটা:** আলাদা RNG stream দিয়ে সিন্থেটিক ওয়ালেট নেটওয়ার্ক বানানো হবে: সাধারণ গ্রাহক, merchant, mule। ৫টা স্ক্যাম প্যাটার্ন ঢোকানো হবে: (১) fan-in mule: অনেক sender থেকে এক ওয়ালেটে টাকা, তারপর দ্রুত cash-out; (২) নতুন খোলা অ্যাকাউন্টে হঠাৎ টাকা; (৩) agent-hopping: একই দিনে ৩টা বা বেশি এজেন্টে cash-out; (৪) structuring: round সংখ্যার ঠিক নিচে বারবার; (৫) রিপোর্ট-হওয়া নম্বর (সিন্থেটিক তালিকা)। প্রতিটা প্যাটার্নের কিছু কঠিন (subtle) সংস্করণও থাকবে। label থাকবে আলাদা টেবিলে, যা শুধু মূল্যায়নে ব্যবহার হবে, কখনো feature-এ যাবে না।
- **Feature (graph ও velocity):** ২৪ ঘণ্টায় কতজন আলাদা sender, ঢোকা টাকার পরিমাণ, শেষ টাকা আসার পর কত মিনিট, অ্যাকাউন্টের বয়স, ২৪ ঘণ্টায় কতগুলো এজেন্টে গেছে, চাওয়া টাকা / ঢোকা টাকা অনুপাত, ঘণ্টা, round-amount flag, reported flag, sender-দের গড় বয়স।
- **মডেল:** LightGBM binary classifier (stack-এ আগে থেকেই আছে), isotonic calibration, তুলনার জন্য logistic regression baseline আর শুধু-rules baseline। split হবে train / validation / blind test (Prompt 2-এর M1-এর মতো)। threshold বাছা হবে শুধু validation-এ। blind test একবারই score করা হবে।
- **ব্যাখ্যা:** TreeSHAP থেকে reason code (বিদ্যমান `ml/explain` ধরনে)। সংখ্যাগুলো আসবে feature-এর আসল মান থেকে।
- **Rules-এর ভূমিকা** (`app/rules/scam_rules.py`): reported নম্বর হলে বা ২৪ ঘণ্টায় ≥ N এজেন্ট হলে স্তর কমপক্ষে "verify" হবে। ML স্তর বাড়াতে পারে। rules ঠিক করে কোন তথ্য দেখানো যাবে।
- **মাপকাঠি (গেট):** blind test-এ PR-AUC শুধু-rules baseline-এর চেয়ে ভালো হতে হবে (gate test)। precision@verify, recall, প্রতি ১০০ সাধারণ গ্রাহকে কত false alarm, Brier score, fairness gap, আর p95 latency ২০০ ms-এর কম।
- **Impact:** blind period-এ ধরা পড়া স্ক্যাম cash-out-এর টাকা (সিন্থেটিক) আর এজেন্টের ক্যাশ কত ঘণ্টা বেশি টিকল। impact calculator-এ নতুন লাইন হিসেবে যাবে, যোগ করা (additive) API দিয়ে।

---

## ৪. কী কী যোগ হবে (tree, প্রতিটার কাজ সহ)

```text
AI_Hackathon_DIU/
├── CLAUDE.md                                  [বদল] F13 এক লাইন + ২টা hard rule + spec-এর লিংক
├── docs/
│   ├── SCAM_GUARD_SPEC.md                     [নতুন] একমাত্র সত্য উৎস: ডেটা, ফিচার, API, rules, UI, মাপকাঠি
│   ├── SCAM_GUARD_PLAN.md                     [এই ফাইল]
│   ├── HACKATHON_BRIEF.md                     [ঐচ্ছিক, তুমি লিখবে] PDF থেকে Track 1-এর শর্ত
│   ├── METHODS.md                             [বদল] §Scam guard: পদ্ধতি, blind metrics, সীমাবদ্ধতা
│   ├── SYNTHETIC_ASSUMPTIONS.md               [বদল] ওয়ালেট নেটওয়ার্ক ও ৫টা প্যাটার্নের অনুমান
│   ├── ARCHITECTURE.md / LLM_SPEC.md          [বদল] নতুন মডিউল, scam_warning wording kind
│   ├── JUDGING_MAP.md / IDEA_CHAIN.md         [বদল] Track 1 সেতু, নতুন পদ্ধতির সারি
│   ├── RESPONSIBLE_AI_CHECKLIST.md            [বদল] no-block, no-accuse, hashing, FP fairness
│   ├── DEMO_SCRIPT.md / DECISIONS.md          [বদল] ৬০ সেকেন্ডের স্ক্যাম ডেমো; সিদ্ধান্তগুলো
│   └── UPGRADE_PROGRESS.md                    [বদল] "Scam guard" অংশ
├── backend/
│   ├── migrations/versions/0024_scam_guard.py [নতুন] wallets, wallet_transfers, wallet_cashouts,
│   │                                           scam_labels, cashout_checks (+ index)
│   ├── app/models/scam.py                     [নতুন] SQLAlchemy মডেল
│   ├── app/schemas/scam.py                    [নতুন] Pydantic: CheckIn, CheckOut, Decision, Watch, Metrics
│   ├── app/rules/scam_rules.py                [নতুন] স্তরের নিয়ম, reason code, কী দেখানো যাবে
│   ├── app/services/scam_check.py             [নতুন] চেক চালানো: hash → aggregates → model → rules → wording
│   ├── app/services/scam_aggregates.py        [নতুন] ওয়ালেট-ভিত্তিক velocity aggregates (incremental)
│   ├── app/services/scam_watch.py             [নতুন] distributor সারাংশ, liquidity link
│   ├── app/core/wallet_hash.py                [নতুন] HMAC (বিদ্যমান secret থেকে HKDF), masking
│   ├── app/api/v1/scam.py                     [নতুন] agent / distributor / admin endpoint
│   ├── app/api/v1/__init__.py                 [বদল] router যোগ
│   ├── app/llm/templates.py + packs.py        [বদল] scam_warning template (bn/en) + evidence pack
│   ├── app/llm/knowledge/11-scam-cashout.md   [নতুন] প্লেবুক: সন্দেহজনক cash-out (DEMO, অফিসিয়াল নয়)
│   ├── app/services/data_scheduler.py         [বদল] tick-এ নতুন ঘণ্টার লেজার (≤ ২ সেকেন্ড)
│   ├── app/services/impact*.py                [বদল, additive] scam_loss_avoided_bdt
│   ├── app/services/model_card*.py            [বদল] স্ক্যাম মডেল এন্ট্রি
│   ├── ml/data_gen/wallets.py                 [নতুন] ওয়ালেট নেটওয়ার্ক (আলাদা RNG stream)
│   ├── ml/data_gen/scam_patterns.py           [নতুন] ৫টা প্যাটার্ন + subtle সংস্করণ, label
│   ├── ml/data_gen/live*.py, load.py          [বদল] fixed ও live (per-date seed, catch-up) দুটোতেই লেজার
│   ├── ml/features/scam.py                    [নতুন] point-in-time feature (ভবিষ্যৎ দেখা নিষেধ)
│   ├── ml/training/scam.py                    [নতুন] LightGBM + isotonic, logistic আর rules baseline
│   ├── ml/inference/scam.py                   [নতুন] লোড, predict, SHAP reasons
│   ├── ml/artifacts/scam_*.joblib/.json       [নতুন, COMMIT হবে] মডেল + manifest (blind metrics)
│   ├── bootstrap.py                           [বদল] লেজার seed + aggregate warm-up
│   └── tests/
│       ├── test_scam_data.py                  [নতুন] determinism, পুরনো ডেটা অপরিবর্তিত (fingerprint)
│       ├── test_scam_features.py              [নতুন] leakage test, point-in-time
│       ├── test_scam_rules.py                 [নতুন] floor rule, wording-এ অভিযোগ নেই
│       ├── test_scam_api.py                   [নতুন] role, scoping, rate limit, audit, masking, latency
│       └── test_scam_model_gate.py            [নতুন, slow] PR-AUC > rules baseline, calibration
├── frontend/src/
│   ├── features/agent/scamCheck/              [নতুন] ScamCheckPage, RiskVerdictCard, ReasonList,
│   │                                           DecisionBar, demo sample chips, *.test.tsx
│   ├── features/agent/home/                   [বদল] ছোট "Scam guard আজ" কার্ড + লিংক
│   ├── features/distributor/scamWatch/        [নতুন] ScamWatchPage, HoppingWalletsTable, *.test.tsx
│   ├── features/admin/models/                 [বদল] স্ক্যাম মডেল কার্ড
│   ├── features/responsibleAi/                [বদল] স্ক্যাম গার্ডের FP fairness সারি
│   ├── api/scam.ts                            [নতুন] Axios + Zod + TanStack hooks
│   ├── app/router.tsx + navigation            [বদল] নতুন route, nav item (lucide ShieldAlert)
│   └── i18n/{bn,en}.json                      [বদল] scamGuard.* keys
└── e2e/
    ├── routes.ts                              [বদল] /agent/scam-check, /distributor/scam-watch
    └── tests/scam-guard.spec.ts               [নতুন] কাউন্টার ফ্লো + distributor দৃশ্য
```

### CLAUDE.md-তে ঠিক এটুকুই যোগ হবে (token বাঁচাতে, বাকি সব spec-এ)
- "The 12 features" লাইনের পরে: `13 Scam-aware cash-out guard (Track 1 bridge): real-time advisory risk check at the agent counter. Spec: docs/SCAM_GUARD_SPEC.md`
- Hard rules-এ: `Scam guard never blocks a transaction, never accuses a customer, never shows sender identities; wallet numbers stored only as HMAC hash + last 3 digits; agent decision -> audit_log.`
- Docs তালিকায়: `SCAM_GUARD_SPEC.md`

---

## ৫. প্রম্পটগুলো (ইংরেজিতে, হুবহু কপি করো)

### S0: প্রস্তুতি আর spec  (Opus 5.5, Medium)

```text
SCAM GUARD S0 - PREP AND SPEC for AgentPulse. Read docs/SCAM_GUARD_PLAN.md sections 2-4 (design, tree, CLAUDE.md lines) and docs/HACKATHON_BRIEF.md if it exists. Do not write feature code in this prompt.

SAFETY RULES (apply to S0-S3)
- No git add/commit/stash/reset/checkout/clean/push. Never open or print .env or keys. Never run run.bat --reset. Never call a live LLM. Only stop processes you started, by exact PID. Anything that mutates data or generates load runs ONLY on the isolated project agentpulse-verify (docker-compose.verify.yml, ports 18000/15173), with -p agentpulse-verify on every compose command that can remove anything. Main stack: read-only.
- Never weaken, skip or delete a test. API changes additive only. Do not change existing data, models, thresholds or business rules.
- Decisions: safest default, recorded in docs/DECISIONS.md (what, why, alternative). After 2 failed attempts at the same issue, log it as open and move on.
- Keep a "Scam guard" section (max 40 lines) in docs/UPGRADE_PROGRESS.md: steps todo/doing/done, one-line result, duration. If it exists, continue from the first unfinished step.

TASKS
1. Write docs/SCAM_GUARD_SPEC.md (max 250 lines) as the single source of truth for S1-S3, from the plan: data model (tables, columns, indexes, migration 0024 after 0023, linear chain), the five scam patterns with their subtle variants and target rates, the independent RNG stream (derived from the fixed seed with its own key; per calendar date in live mode), point-in-time feature list, model and baselines, train/validation/blind-test split, gates, reason codes with bn/en wording templates, API contract (paths, roles, request/response fields incl. model_version and generated_at), hashing and masking, rate limit, audit events, UI screens and states, latency budget (p95 < 200 ms per check; tick addition <= 2 s), responsible-AI rules, and a test list. Check that every name in it matches the existing code conventions (grep the repo; do not read whole files).
2. Edit CLAUDE.md with exactly the three additions in plan section 4. Nothing else.
3. Make the fast pytest step limit in scripts/check.ps1 configurable: param -PytestTimeout, else env CHECK_PYTEST_TIMEOUT, else 420, same style as -E2ETimeout. Update the header comment and docs/COMMANDS.md. Run `scripts\check.ps1 -Backend` once with COMPOSE_PROJECT_NAME=agentpulse-verify and report the pytest duration.
4. Write the fixed-mode data fingerprint helper (or reuse the one from the live clock work) as a test helper so S1 can prove the existing tables are byte-identical. Record its current values in UPGRADE_PROGRESS.md.

REPORT: files changed, the check result with duration, open questions. Simple English.
```

### S1: ডেটা আর ML  (Opus 5.5, High)

```text
SCAM GUARD S1 - DATA AND ML. Follow docs/SCAM_GUARD_SPEC.md exactly; same SAFETY RULES as in docs/SCAM_GUARD_PLAN.md S0. If the spec is wrong or impossible, fix the spec first and log the decision.

1. Migration 0024 + app/models/scam.py, as in the spec.
2. ml/data_gen/wallets.py and scam_patterns.py: synthetic wallet network and the five patterns, using an INDEPENDENT RNG stream only. Plug it into the fixed-mode loader and the live-mode generator, catch-up and hourly tick (per-date deterministic, idempotent, no future rows). Keep the row volume small enough that seeding adds <= 30 s on the verify stack and the tick adds <= 2 s; measure both.
3. Prove non-interference: the S0 fingerprint of every existing table is identical before and after; the existing ML gates still pass.
4. ml/features/scam.py (point-in-time, no future rows, labels never used as features), ml/training/scam.py (LightGBM classifier + isotonic calibration, logistic and rules-only baselines; threshold on validation only; blind test scored once), ml/inference/scam.py (predict + TreeSHAP reason codes). Back up nothing else; only ADD the new artifacts scam_*.joblib and scam_manifest.json with metrics labelled "synthetic data".
5. Tests: data determinism, fingerprint unchanged, leakage test, rules floor, slow gate test (blind PR-AUC beats rules-only baseline; Brier reported). Mark training and full-data tests @pytest.mark.slow.
6. Run on the isolated stack: `check.ps1 -Backend`, then `-Slow` once at the end. Long commands run in the background with a log file.

REPORT (simple English): blind-test metrics table (never invent a number) vs both baselines, seed time and tick time added, fingerprint result, files changed, NOT FIXED AND REMAINING PROBLEMS (numbered, with severity), decisions.
```

### S2: Backend API, rules, wording  (Opus 5.5, Medium)

```text
SCAM GUARD S2 - BACKEND. Follow docs/SCAM_GUARD_SPEC.md; same SAFETY RULES as in docs/SCAM_GUARD_PLAN.md S0. S1 must be done (check docs/UPGRADE_PROGRESS.md); if not, stop and say so.

1. app/core/wallet_hash.py (HMAC keyed from the existing secret via HKDF, masking to the last 3 digits; the raw number is never stored or logged), app/rules/scam_rules.py, app/services/scam_aggregates.py, scam_check.py, scam_watch.py, schemas, and app/api/v1/scam.py with the spec endpoints: agent check, agent decision (audit_log with user id + note), agent today summary, demo sample numbers (DEMO_MODE only), distributor watch (own agents only), admin metrics. Roles are checked server-side; agents never see sender identities or other agents' checks; per-agent rate limit using the existing shared limiter; every response carries model_version and generated_at.
2. Wording: a scam_warning template (bn/en) in app/llm/templates.py plus an evidence pack. LLM polish is optional through the existing guard (numbers guard, Bangla digits, fallback, llm_call_log). The wording must say "verify", never accuse. Add knowledge/11-scam-cashout.md marked DEMO playbook, no official upay fees, limits or hotlines; use the OFFICIAL_SUPPORT_NOTE style placeholder.
3. Liquidity link and impact: the distributor watch shows the declined flagged cash-out amount; impact gets an additive scam_loss_avoided_bdt (blind period, synthetic). Model card and responsible-AI panel data get a scam guard entry with FP rate by district and urban/rural.
4. Tests for every endpoint: roles, cross-agent and cross-distributor isolation, masking (no raw number in responses, logs or DB), rate limit, audit row, decision validation, p95 < 200 ms for 100 checks on the verify stack, wording has no accusation words (bn and en), template mode works without a key.
5. Run `check.ps1 -Backend` on the isolated stack.

REPORT (simple English): endpoints added, measured p95, files changed, NOT FIXED AND REMAINING PROBLEMS (numbered, with severity), decisions.
```

### S3: Frontend, e2e, docs  (Sonnet 5.5, High)

```text
SCAM GUARD S3 - FRONTEND, E2E, DOCS. Follow docs/SCAM_GUARD_SPEC.md, docs/DESIGN.md and docs/PRODUCT_CHECKLIST.md; same SAFETY RULES as in docs/SCAM_GUARD_PLAN.md S0. S2 must be done; if not, stop.

1. frontend/src/api/scam.ts (Axios + Zod + TanStack Query, no `any`).
2. /agent/scam-check: a counter-first screen that works on a 390 px phone: wallet number input (masked display), amount, check button; RiskVerdictCard (level colour from the design tokens plus text and an icon, never colour alone), up to 3 reasons with numbers, steps to take, "advisory: you decide" label, generated_by label, model_version/time; DecisionBar (proceeded / verified and proceeded / declined / reported, optional note). Demo sample chips only in DEMO_MODE. Skeleton, empty, error-with-retry states; reduced motion; bn/en; lucide icons only (ShieldAlert, ShieldCheck).
3. Agent home: a small "Scam guard today" card linking to the screen. Navigation item for agents.
4. /distributor/scam-watch: today's high-risk checks by agent, wallets seen at several agents (masked), declined amount and its effect on cash, all with the same states. Admin models page and responsible-AI panel: the scam guard entries.
5. Add both routes to e2e/routes.ts. Write e2e/tests/scam-guard.spec.ts: agent checks a demo high-risk number, sees the Bangla warning and reasons, records "declined", the distributor sees it on the watch page. Vitest tests for each new component.
6. Docs: METHODS, SYNTHETIC_ASSUMPTIONS, ARCHITECTURE, LLM_SPEC, JUDGING_MAP (Track 05 primary, Track 1 bridge), IDEA_CHAIN, RESPONSIBLE_AI_CHECKLIST, DEMO_SCRIPT (a 60 second scam demo), README feature list. Use only the measured numbers from S1/S2.
7. Run on the isolated stack: `check.ps1 -Frontend`, then `-Up -E2E` once at the end.

FINAL REPORT (simple English, for a beginner):
1. Status per step S0-S3: ALL OK or NOT OK.
2. Measured numbers (blind metrics, p95, seed and tick time added). Never invent a number.
3. Changed and new files (from git status; nothing committed).
4. NOT FIXED AND REMAINING PROBLEMS: numbered, severity, how to see it, what to do next. If none, write "No remaining problems". Do not soften anything.
5. Decisions made for me.
6. What I must check by hand in a browser (Bangla and English, phone width).
```

### মাঝপথে থেমে গেলে (যেকোনো S প্রম্পটে)

```text
Read docs/UPGRADE_PROGRESS.md (Scam guard section), docs/SCAM_GUARD_SPEC.md and docs/DECISIONS.md. Continue the scam guard work from the first unfinished step (S0-S3) with the same SAFETY RULES as in docs/SCAM_GUARD_PLAN.md S0. Do not redo finished steps. End with the report format of the step you finish.
```

### FIX প্রম্পট: Prompt 1 আর 2-এর বাকি সমস্যা (স্ক্যাম গার্ডের পরে, commit করে নিয়ে)  (Opus 5.5, Medium)

```text
FIX REMAINING UPGRADE ISSUES for AgentPulse. Same SAFETY RULES as docs/SCAM_GUARD_PLAN.md S0 (isolated agentpulse-verify stack, no git writes, no .env, no live LLM, no test weakening). Keep the scam guard working: its tests must stay green.
Fix in this order, measure before and after, and stop cleanly when a fix needs a decision only I can make:
1. Tick budget: move the daily impact backtest out of the hourly tick into its own low-priority daily job (leader-guarded), then profile the forecast and risk steps and compute the refill-aware view less often, so every tick, including the first after midnight, stays under 60 s on 300 agents. Report the timings.
2. Anomaly: switch the anomaly "refills" feature to the ledger-based detector that ml/.../refill.py uses; retrain only on the train period, choose settings on validation, score the blind test once, and report recall per anomaly style. Never tune on the test period. Keep the old artifacts as default if the result is worse.
3. Joint stockout: re-tune the alert cut on the validation period; make the joint method the default only if blind recall is not lower than the current default.
4. Cash-in bands and tier-3 coverage: per-group conformal calibration on validation; report coverage before and after.
5. Live mode: prune snapshot rows older than the 120-day window in the daily job, keep is_holdout consistent, cap the demo story list in system_meta.
6. Low items if time remains: show refill_aware in the agent stockout UI, add PyYAML to requirements.txt, helper-model recalibration (keep the better ECE).
Run -Backend after each fix, -Slow and -Up -E2E once at the end. FINAL REPORT in the same format as the upgrade prompts, including NOT FIXED AND REMAINING PROBLEMS.
```

### Prompt 3 (Copilot) দেওয়ার সময় শুধু এই লাইনটা প্রম্পটের PHASE 4-এর শেষে যোগ করো

```text
- Scam guard integration: add intents "is this cash-out suspicious", "what to do with a suspicious customer" and "my scam checks today", using a read-only scam-guard tool (the agent's own checks and summary only, masked numbers, never sender identities, never a block or an accusation). Add Bangla, English and Banglish golden cases for them (e.g. "ei number e onek taka asche", "scam naki", "cash out dibo?").
```

---

## ৬. শেষে তুমি হাতে যা দেখবে
1. `/agent/scam-check`-এ demo high-risk নম্বর দাও। বাংলা সতর্কবার্তা আসছে কিনা, "৮ জন পাঠিয়েছে"-ধরনের সংখ্যা মিলছে কিনা, আর "সিদ্ধান্ত আপনার" লেখা আছে কিনা দেখো।
2. একটা সাধারণ নম্বর দাও। সবুজ বা low আসছে কিনা দেখো, অকারণে ভয় দেখাচ্ছে কিনা খেয়াল করো।
3. "ফিরিয়ে দিয়েছি" চাপো। তারপর distributor হিসেবে login করে `/distributor/scam-watch`-এ সেটা আসছে কিনা দেখো। admin হিসেবে audit log-এও দেখো।
4. ফোনের মাপে (৩৯০ px) আর ইংরেজিতে একবার করে দেখো।
5. Judge-দের জন্য: README আর JUDGING_MAP-এ যেন লেখা থাকে **"Track 05 primary, Track 1 bridge"**। মূল track বদলে গেছে, এমন যেন না মনে হয়।
