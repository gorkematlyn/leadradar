# Advertising providers: access verification

Each platform is an independent module in `leadradar/modules/advertising/providers/`, with its own configuration, research logic, parser, status handling and rate limit. LeadRadar never fabricates advertising results and never estimates spend, impressions or performance. `no_results` means nothing matched within the documented search scope, not that the company never advertises.

The table below reflects what was verified while building this release (November 2026). Platform terms change, so re-verify before enabling any automation.

| Platform | Automated research | Why | Manual path |
|---|---|---|---|
| **Meta** | Supported **only through the official Ad Library API** (`graph.facebook.com/{version}/ads_archive`) when an administrator stores an access token from an identity-verified Meta developer account. | The official API exists. `ad_type=ALL` covers all ads only for delivery in the EU (DSA); elsewhere it covers political and issue ads only, and the stored search scope records this limitation. The Ad Library website is not scraped. | Official Ad Library link (prefilled search) plus a verified manual entry. |
| **Google** | Unsupported | The Ads Transparency Center has no public API and Google's terms don't allow automated scraping. A BigQuery public dataset exists, but it covers advertisers serving in the EEA/Türkiye only and needs a Google Cloud account, so it is not used by default. | Prefilled `adstransparency.google.com/?domain=` link plus a manual entry. |
| **LinkedIn** | Unsupported | LinkedIn's User Agreement prohibits scraping. The Advertiser Transparency API requires an approved developer application and member OAuth. | Ad Library search link plus a manual entry. |
| **TikTok** | Unsupported (by default) | The Commercial Content API requires an approved research or developer application. | `library.tiktok.com` link plus a manual entry. |
| **Microsoft** | Unsupported (pending verification) | Microsoft documents a public Ad Library API for EU/EEA ads. Its request parameters could not be verified from the build environment, so the provider stays manual until it is implemented and tested against Microsoft's documentation. | `adlibrary.ads.microsoft.com` link plus a manual entry. |
| **ChatGPT (OpenAI)** | Unsupported | No public ChatGPT ad library or transparency research source was found (late 2026). The Ads Manager only shows an advertiser's own campaigns. | Manual entry if the ad is verified from another legitimate source. |
| **Apify** (optional) | Supported with budgets | This is a generic Actor runner using the official Apify API. Inputs are allow-listed, and every run is blocked unless daily, monthly and per-task budgets are configured and not exceeded. Estimated and provider-reported costs are tracked separately. Check the Actor's own terms and the target platform's terms before using an Actor. | n/a |

## Matching
Results are matched to companies by name similarity and, more strongly, by the company's verified domain appearing in ad landing captions. A result is confirmed automatically only when exactly one advertiser matches the domain with high confidence. Every other case becomes `match_required` and needs administrator confirmation. Only confirmed advertisers with active ads affect scores.

## Rate limits
Each provider has its own per-minute limit (default 6). Jobs that exceed it are rescheduled and marked `rate_limited`. LeadRadar never works around CAPTCHAs, logins or platform rate limits.
