export interface User {
  id: string;
  email: string;
  display_name: string;
  role: string;
  totp_enabled: boolean;
  locale: "en" | "tr";
  theme: "light" | "dark" | "system";
  table_preferences: Record<string, unknown>;
  sidebar_collapsed: boolean;
}

export interface CompanyRow {
  id: string;
  name: string;
  website: string | null;
  domain: string | null;
  country: string | null;
  city: string | null;
  industry: string | null;
  industry_confidence: string;
  lead_score: number | null;
  preliminary_score: number | null;
  final_score: number | null;
  classification: string | null;
  confidence: number | null;
  website_status: string;
  advertising_platforms: string[];
  services: { key: string; score: number; provisional: boolean }[];
  tags: { id: string; name_en: string; name_tr: string; color: string }[];
  crm_status: string;
  analysis_status: string;
  last_audit_at: string | null;
  do_not_contact: boolean;
  archived: boolean;
  watchlisted: boolean;
  follow_up_at: string | null;
}

export interface CompanyFilter {
  q?: string;
  countries?: string[];
  regions?: string[];
  cities?: string[];
  industries?: string[];
  score_min?: number | null;
  score_max?: number | null;
  confidence_min?: number | null;
  confidence_max?: number | null;
  classifications?: string[];
  ad_platforms?: string[];
  ad_mode?: "any" | "all";
  website_status?: string[];
  tracking_detected?: string[];
  tracking_not_detected?: string[];
  services?: string[];
  service_min?: number;
  crm_status?: string[];
  analysis_status?: string[];
  tags_any?: string[];
  tags_all?: string[];
  tags_exclude?: string[];
  audit_from?: string | null;
  audit_to?: string | null;
  dnc?: "exclude" | "include" | "only";
  archived?: "exclude" | "include" | "only";
  watchlisted?: boolean | null;
  industry_confidence?: "confident" | "review" | null;
  has_website?: boolean | null;
}

export interface Country {
  iso2: string;
  iso3: string;
  name_en: string;
  name_tr: string;
  region: string;
  flag: string;
  enabled: boolean;
  is_priority: boolean;
  import_status: string;
  progress: ImportProgress | null;
  last_import_at: string | null;
  last_source_timestamp: string | null;
  geofabrik_ids: string[] | null;
  companies: number;
}

export interface Industry {
  id: string;
  key: string;
  name_en: string;
  name_tr: string;
  description_en: string;
  description_tr: string;
  enabled: boolean;
  priority: number;
  is_priority: boolean;
  relevant_services: string[];
  relevant_features: string[];
  applicable_audit_rules: string[];
  review_template_id: string | null;
  scoring_profile_id: string | null;
  rules: { id: string; key: string; description: string; conditions: Record<string, unknown>; classification: string; enabled: boolean }[];
}

export interface ImportProgress {
  status: string;
  job_id: string;
  regions_total: number;
  regions_done: number;
  regions_failed: number;
  regions_cancelled: number;
  bytes_total: number | null;
  bytes_done: number | null;
  current: { job_id: string; name: string | null; stage: string | null; processed: number | null; total: number | null } | null;
  error: string | null;
  started_at: string;
}

export interface Tag {
  id: string;
  name_en: string;
  name_tr: string;
  description_en: string | null;
  description_tr: string | null;
  color: string;
  count: number;
}

export interface Job {
  id: string;
  type: string;
  name: string;
  queue: string;
  status: string;
  priority: number;
  stage: string | null;
  processed: number;
  total: number | null;
  attempts: number;
  max_attempts: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
  run_at: string;
  cancel_requested: boolean;
  company_id: string | null;
  parent_id: string | null;
  resource_class: string;
}

export const SERVICES = [
  "website_design", "website_redesign", "landing_page", "ui_ux", "graphic_design", "brand_identity",
  "social_media_design", "ad_creative", "meta_ads", "google_ads", "linkedin_ads", "conversion_tracking",
  "technical_seo", "ecommerce_optimization",
] as const;

export const CRM_STATUSES = [
  "new", "qualified", "shortlisted", "contacted", "replied", "meeting", "proposal_sent", "won", "lost",
  "not_a_fit", "do_not_contact", "archived",
] as const;

export const ANALYSIS_STATUSES = ["not_analyzed", "queued", "running", "action_required", "completed", "failed", "cancelled"] as const;
export const AD_PLATFORMS = ["meta", "google", "linkedin", "tiktok", "microsoft", "openai"] as const;
export const TRACKING_TECH = [
  "gtm", "ga4", "google_ads_conversion", "google_ads_remarketing", "google_consent_mode", "meta_pixel",
  "linkedin_insight", "tiktok_pixel", "microsoft_uet", "pinterest_tag", "microsoft_clarity", "hotjar", "cmp",
] as const;
export const WEBSITE_STATUSES = ["unverified", "verified", "not_found", "verified_absent"] as const;
export const CLASSIFICATIONS = ["high_priority", "strong_potential", "requires_review", "low_priority", "excluded"] as const;
