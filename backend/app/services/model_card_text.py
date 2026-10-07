"""Fixed model-card wording (bn / en). Numbers never live here; they come from the registry."""

from app.models.enums import Lang

Text = dict[Lang, str]
TextList = dict[Lang, list[str]]

SOURCE: Text = {
    Lang.en: "Fully synthetic hourly agent data from a seeded generator; no real customer or "
             "agent data. Patterns are documented assumptions, not measured upay behaviour.",
    Lang.bn: "বীজ-নির্দিষ্ট জেনারেটর থেকে তৈরি সম্পূর্ণ কৃত্রিম ঘণ্টাভিত্তিক এজেন্ট ডেটা; কোনো "
             "আসল গ্রাহক বা এজেন্টের ডেটা নেই। প্যাটার্নগুলো নথিভুক্ত অনুমান, upay-এর মাপা আচরণ নয়।",
}

HUMAN_OVERSIGHT: Text = {
    Lang.en: "Advisory only. The system recommends; a distributor approves or rejects every swap, "
             "request and anomaly review with a note in the audit log. Nothing moves money.",
    Lang.bn: "শুধু পরামর্শ। সিস্টেম সুপারিশ করে; প্রতিটি সোয়াপ, অনুরোধ ও অস্বাভাবিকতা পর্যালোচনা "
             "ডিস্ট্রিবিউটর নোটসহ অনুমোদন বা বাতিল করেন, যা অডিট লগে থাকে। কোনো টাকা নিজে থেকে নড়ে না।",
}

FORECAST_KIND: Text = {
    Lang.en: "LightGBM quantile regression (q10 / q50 / q90), one model per demand type",
    Lang.bn: "LightGBM কোয়ান্টাইল রিগ্রেশন (q10 / q50 / q90), প্রতিটি চাহিদার জন্য আলাদা মডেল",
}
FORECAST_PURPOSE: Text = {
    Lang.en: "Hourly cash-out and cash-in demand per agent for the next 72 hours; drives "
             "time-to-stockout, risk levels and rebalance amounts.",
    Lang.bn: "প্রতিটি এজেন্টের পরের ৭২ ঘণ্টার ঘণ্টাভিত্তিক ক্যাশ-আউট ও ক্যাশ-ইন চাহিদা; এখান থেকেই "
             "ফুরিয়ে যাওয়ার সময়, ঝুঁকির মাত্রা ও রিব্যালান্সের পরিমাণ আসে।",
}
ANOMALY_KIND: Text = {
    Lang.en: "Isolation Forest per peer group (tier x area) on peer-relative weekly features",
    Lang.bn: "সমগোত্রীয় দল (টিয়ার x এলাকা) অনুযায়ী Isolation Forest, সমগোত্রের তুলনায় সাপ্তাহিক বৈশিষ্ট্যে",
}
ANOMALY_PURPOSE: Text = {
    Lang.en: "Flags unusual agent activity as a lead for human review; never an accusation.",
    Lang.bn: "অস্বাভাবিক এজেন্ট কার্যকলাপ মানুষের পর্যালোচনার জন্য চিহ্নিত করে; এটি কখনো অভিযোগ নয়।",
}

HELPER_KIND: Text = {
    Lang.en: "Logistic regression with Platt calibration, learned from SIMULATED helper "
             "behaviour only",
    Lang.bn: "প্ল্যাট ক্যালিব্রেশনসহ লজিস্টিক রিগ্রেশন, শুধু সিমুলেটেড সাহায্যকারীর আচরণ থেকে শেখা",
}
HELPER_PURPOSE: Text = {
    Lang.en: "Chance that an asked helper agrees to a liquidity help request. Optional (off by "
             "default): it may only order or size waves among the helpers the rules already "
             "allow; it never adds or removes a helper.",
    Lang.bn: "অনুরোধ পাওয়া সাহায্যকারী রাজি হওয়ার সম্ভাবনা। ঐচ্ছিক (শুরুতে বন্ধ): নিয়ম যাদের অনুমতি "
             "দেয় শুধু তাদের ক্রম বা প্রতি ধাপে কতজনকে জিজ্ঞেস করা হবে তা ঠিক করতে পারে; কাউকে "
             "যোগ বা বাদ দেয় না।",
}

INTENDED_USE: TextList = {
    Lang.en: [
        "Help MFS agents see when their cash or e-money float may run out, and why.",
        "Help distributors plan top-ups, agent-to-agent swaps and van routes before stockouts.",
        "Give reviewers a queue of unusual agent activity to look at.",
    ],
    Lang.bn: [
        "এজেন্টকে দেখানো কখন ক্যাশ বা ই-মানি ফ্লোট ফুরিয়ে যেতে পারে, এবং কেন।",
        "ফুরিয়ে যাওয়ার আগেই ডিস্ট্রিবিউটরকে টপ-আপ, এজেন্ট-থেকে-এজেন্ট সোয়াপ ও ভ্যান রুট পরিকল্পনায় সাহায্য।",
        "পর্যালোচকদের জন্য অস্বাভাবিক এজেন্ট কার্যকলাপের তালিকা দেওয়া।",
    ],
}

OUT_OF_SCOPE: TextList = {
    Lang.en: [
        "Moving money, approving swaps or blocking agents automatically.",
        "Judging fraud: an anomaly flag is a lead for review, not evidence.",
        "Credit, pricing or any decision about an individual customer.",
        "Use on real data before re-training and re-validation on that data.",
    ],
    Lang.bn: [
        "স্বয়ংক্রিয়ভাবে টাকা পাঠানো, সোয়াপ অনুমোদন বা এজেন্ট বন্ধ করা।",
        "প্রতারণা নির্ধারণ: অস্বাভাবিকতার চিহ্ন শুধু পর্যালোচনার সূত্র, প্রমাণ নয়।",
        "ঋণ, মূল্য নির্ধারণ বা কোনো একক গ্রাহক সম্পর্কে সিদ্ধান্ত।",
        "আসল ডেটায় নতুন করে প্রশিক্ষণ ও যাচাই ছাড়া ব্যবহার।",
    ],
}

LIMITATIONS: TextList = {
    Lang.en: [
        "Trained and tested on synthetic data only; metrics show method soundness, "
        "not real-world accuracy.",
        "The forecast learns served demand, so hours when a float was already empty are "
        "under-stated.",
        "Risk levels assume no refill in the window (conservative). A refill-aware reading "
        "from each agent's own refill habit is shown beside it but never drives a decision.",
        "Weather of the target day is taken as known (a perfect weather forecast).",
        "Impact figures come from a simulated replay of 14 held-out days with documented cost "
        "assumptions, not from a field trial.",
        "Anomaly detection was tested on three injected patterns only; real fraud differs.",
        "The helper acceptance model is learned from simulated behaviour; it needs real "
        "response data before any claim about real helpers.",
        "Forecast bands are calibrated on the 14 days before the test period; coverage holds "
        "only while demand behaves like those days.",
    ],
    Lang.bn: [
        "শুধু কৃত্রিম ডেটায় প্রশিক্ষিত ও পরীক্ষিত; মেট্রিক পদ্ধতির যথার্থতা দেখায়, বাস্তব নির্ভুলতা নয়।",
        "পূর্বাভাস পরিবেশিত চাহিদা থেকে শেখে, তাই ফ্লোট খালি থাকার ঘণ্টাগুলোর চাহিদা কম দেখায়।",
        "ঝুঁকির মাত্রায় ধরা হয় সময়ের মধ্যে কোনো রিফিল হবে না (সতর্ক হিসাব)। প্রত্যেক এজেন্টের "
        "নিজের রিফিলের অভ্যাস ধরে একটি আলাদা হিসাব পাশে দেখানো হয়, কিন্তু সিদ্ধান্তে ব্যবহার হয় না।",
        "লক্ষ্য দিনের আবহাওয়া জানা ধরা হয় (নিখুঁত আবহাওয়া পূর্বাভাস)।",
        "প্রভাবের সংখ্যা ১৪টি আলাদা রাখা দিনের সিমুলেশন থেকে, নথিভুক্ত খরচের অনুমানসহ; মাঠ পরীক্ষা নয়।",
        "অস্বাভাবিকতা শনাক্তকরণ শুধু তিনটি কৃত্রিম প্যাটার্নে পরীক্ষিত; আসল প্রতারণা ভিন্ন হয়।",
        "সাহায্যকারী রাজি হওয়ার মডেল সিমুলেটেড আচরণ থেকে শেখা; আসল সাহায্যকারী নিয়ে কিছু বলার "
        "আগে আসল উত্তরের ডেটা লাগবে।",
        "পূর্বাভাসের সীমা পরীক্ষার আগের ১৪ দিনে মিলিয়ে নেওয়া; চাহিদা সেই দিনগুলোর মতো থাকলেই "
        "সীমার নির্ভরযোগ্যতা টেকে।",
    ],
}
