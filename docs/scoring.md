# Scoring methodology

All scoring is deterministic and reproducible from stored evidence. Recalculating never repeats external research.

## Signals
Evidence becomes **signals** in `modules/scoring/service.py`:
- A failed audit finding emits the signals its audit rule declares (`audit_rules.emits_signals`), but only if the rule applies to the company's industry and the result is `failed`. `unknown`, `blocked`, `error`, `not_checked` and `not_applicable` never emit deficiency signals, and neither does a finding the reviewer marked invalid.
- Heuristic visual signals (`mobile.layout_problems`) count in the **final** score only when the reviewer confirms the visual findings, or validates the individual finding.
- `website.verified_absent` exists only after a manual verification. A missing OSM `website` tag gives `not_found`, which earns no points.
- Advertising signals (`ads.<platform>_active`) require a `found` research result with verified active ads, and either an administrator-confirmed advertiser match or a manual verified entry.
- Review answers emit the question's `yes_signal` or `no_signal` (for example `review.visual_redesign` or `review.unsuitable`).

## Lead score
```
Category score = min(category maximum, sum of valid rule contributions)
Lead score     = clamp(sum of category scores − penalties, 0, 100)
```
The default category maximums are Service Need 35, Commercial Activity 30, Target Fit 20 and Contactability 15. The default rules and points are the ones in the brief and are seeded per profile (`seeds/defaults.py`).
- **Overlap control:** rules in the same `exclusive_group` count only the largest contribution. Website-quality rules carry `requires_absent: [website.verified_absent]`, so a company without a website earns no performance, mobile or SEO failure points.
- **Penalties:** chain or franchise −15 (only when flagged, for example by an OSM `brand:wikidata` tag or the administrator; size alone never triggers it), and confirmed unsuitable −20.
- **Exclusions** take precedence: permanently closed, excluded industry, excluded domain, Do Not Contact, or administrator-rejected. The classification becomes `excluded`.
- **Classification** thresholds are 80, 60 and 40 (editable). A score of 80 or more is labelled *High priority* only when confidence is at least the profile minimum (default 50); otherwise it becomes *Requires review*.
- Preliminary scores (after the automated audit) and final scores (after review) are stored separately. A manual override keeps the calculated score and records who set it, why and when.

## Confidence score
This is a weighted average of evidence-quality components, each between 0 and 1: source reliability 15, identity verification 15, applicable audit coverage 20, website analysis completeness 15, advertising research coverage 10, evidence availability 10, administrator review 10, data freshness 5. Audit coverage counts only applicable checks: `not_applicable` results are excluded from the denominator. **Confidence measures evidence quality, not the probability of winning a client.**

## Service opportunity scores
Each service score adds up `service_rules` whose signal is present, whose `requires_all` signals are all present, and whose `requires_absent` signals are all missing, capped at 100. These rules encode combinations, for example "active Meta ads and Meta Pixel not detected → conversion tracking verification". Rules that depend on subjective assessments (`needs_review`) keep the service **provisional** until the review is complete.

## Profiles
There are eight seeded profiles: General, Website Design, Digital Marketing, Meta Ads, Google Ads, Graphic Design, Brand Identity and E-commerce. They share the rule set with different point weights and service focus. Profiles can be cloned and edited. Every rule edit increments both the rule version and the profile version, and each stored score records the profile version it used. The company page can preview a score under another profile without saving it.

## Explainability
Each stored `lead_scores.breakdown` contains, per category, the applied rules, points, signals and evidence references (finding IDs, review answers, research runs). It also records the category limits and capping, the penalties, exclusions, overlapping rules that were not counted, the confidence components, the profile, the stage and the calculation time. The UI shows all of this.
