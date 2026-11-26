import type { CompanyRow } from "@/lib/types";

export interface ScoreRuleView {
  key: string;
  signal: string;
  points: number;
  title_en: string;
  title_tr: string;
  explanation_en: string;
  explanation_tr: string;
  version: number;
  evidence: string[];
}

export interface ScoreBreakdown {
  formula: string;
  categories: Record<string, { limit: number; raw: number; score: number; capped: boolean; rules: ScoreRuleView[] }>;
  subtotal: number;
  penalties: ScoreRuleView[];
  penalty_total: number;
  exclusions: ScoreRuleView[];
  suppressed_overlaps: { key: string; reason: string; kept: string }[];
  signals: string[];
  confidence: { score: number; components: Record<string, { value: number; weight: number }>; note: string };
  profile: { id: string; key: string; version: number };
  stage: string;
  recommendations: { service: string; rule: string; points: number; text_en: string; text_tr: string; provisional: boolean }[];
}

export interface CompanyDetail extends CompanyRow {
  legal_name: string | null;
  region: string | null;
  address: string | null;
  postal_code: string | null;
  latitude: number | null;
  longitude: number | null;
  email: string | null;
  email_verified: boolean;
  phone: string | null;
  notes: string | null;
  discovered_at: string | null;
  last_verified_at: string | null;
  is_chain: boolean | null;
  permanently_closed: boolean;
  rejected: boolean;
  additional_industries: string[];
  field_sources: Record<string, { source: string; at: string; confirmed: boolean }>;
  service_scores_detail: { service: string; score: number; provisional: boolean; rules: { key: string; points: number; signal: string; needs_review: boolean }[] }[];
  score: { id: string; stage: string; score: number; classification: string; confidence: number; breakdown: ScoreBreakdown; calculated_at: string; profile_version: number } | null;
  override: { score: number; original: number | null; reason: string; created_at: string } | null;
  sources: { source: string; source_key: string; source_url: string | null; source_timestamp: string | null; last_seen_at: string | null }[];
  social_profiles: { id: string; platform: string; handle: string; url: string; verified: boolean; source: string }[];
}

export interface AuditFindingView {
  id: number;
  rule_key: string;
  result: string;
  page_url: string;
  value: Record<string, unknown>;
  confidence: number;
  params: Record<string, unknown>;
  admin_validated: boolean | null;
  rule_version: number;
  evidence_count: number;
  category: string | null;
  severity: string | null;
  title_en: string;
  title_tr: string;
  description_en: string;
  description_tr: string;
  recommendation_en: string;
  recommendation_tr: string;
  heuristic: boolean;
}

export interface AuditDetail {
  id: string;
  mode: string;
  status: string;
  start_url: string | null;
  final_url: string | null;
  created_at: string;
  automated_completed_at: string | null;
  completed_at: string | null;
  reused_from: string | null;
  error: string | null;
  job_id: string | null;
  company: { id: string; name: string; website: string | null; industry: string | null } | null;
  pages_audited: string[];
  metrics: {
    http?: { status: number; elapsed_ms: number; bytes: number; redirects: number };
    lighthouse?: { scores: Record<string, number | null>; metrics: Record<string, number | null>; error: string | null };
    browser?: Record<string, { status: number | null; error: string | null }>;
  };
  context: Record<string, unknown> & { browser?: { version?: string; viewports?: { name: string; width: number; height: number }[] }; lighthouse?: Record<string, unknown>; consent_test?: { clicked_selector: string; note: string } };
  technologies: { key: string; name: string; evidence: string[]; confidence: number; method: string }[];
  findings: AuditFindingView[];
  tracking: { technology: string; status: string; consent_state: string; methods: string[]; evidence_urls: string[]; identifiers: string[]; confidence: number; limitations: string | null; page_url: string | null }[];
  screenshots: { id: string; label: string; viewport: string | null; blob_id: string; approved_for_reports: boolean }[];
  responses: Record<string, { answer: string; note: string | null }>;
  questions: { key: string; text_en: string; text_tr: string }[];
}
