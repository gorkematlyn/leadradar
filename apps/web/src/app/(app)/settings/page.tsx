"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Suspense, useState } from "react";
import { toast } from "sonner";
import { DateText, PageHeader } from "@/components/app/bits";
import { SettingsForm } from "@/components/app/settings-form";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Badge, Callout, Card, CardHeader, Checkbox, InfoTip, Progress, Switch, Tooltip } from "@/components/ui/misc";
import { Dialog, Tabs } from "@/components/ui/overlay";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { type CrmStatusItem, useCrmStatuses, useLocalizedName } from "@/hooks/use-catalog";
import { useSession } from "@/hooks/use-session";
import { api } from "@/lib/api";
import { fmtBytes } from "@/lib/utils";

function useAct() {
  const t = useTranslations();
  const qc = useQueryClient();
  const err = useErrorMessage();
  return async (fn: () => Promise<unknown>, invalidate: string[] = [], msg: string = t("common.saved")) => {
    try {
      const r = await fn();
      invalidate.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      if (msg) toast.success(msg);
      return r;
    } catch (e) {
      toast.error(err(e));
      return null;
    }
  };
}

function GeneralTab() {
  const t = useTranslations("settings");
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader title={t("domain")} description={t("reportOriginHint")} />
        <div className="p-4"><SettingsForm keys={["security.allowed_hosts", "report.public_origin"]} labels={{ "security.allowed_hosts": t("allowedHosts"), "report.public_origin": t("reportOrigin") }} /></div>
        <p className="border-t border-border px-4 py-2 text-[12px] text-muted">{t("allowedHostsHint")}</p>
      </Card>
      <Card>
        <CardHeader title={t("branding")} />
        <div className="p-4"><SettingsForm keys={["report.branding_name", "report.branding_contact"]} labels={{ "report.branding_name": "Brand", "report.branding_contact": "Contact" }} /></div>
      </Card>
      <Card>
        <CardHeader title={t("groups.scoring")} />
        <div className="p-4"><SettingsForm keys={["discovery.priority_countries", "scoring.excluded_domains", "scoring.default_profile"]} labels={{ "discovery.priority_countries": t("priorityCountries"), "scoring.excluded_domains": t("excludedDomains") }} /></div>
      </Card>
    </div>
  );
}

function AccountTab() {
  const t = useTranslations();
  const act = useAct();
  const { data: session } = useSession();
  const { data: sessions } = useApi<{ id: string; created_at: string; last_seen_at: string; ip: string; user_agent: string | null; current: boolean }[]>(["sessions"], "/auth/sessions");
  const [pw, setPw] = useState({ current: "", next: "" });
  const [totp, setTotp] = useState<{ secret: string; qr_svg: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [disable, setDisable] = useState({ open: false, password: "", code: "" });
  const qc = useQueryClient();
  const user = session?.user;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title={t("settings.changePassword")} />
        <form className="grid gap-3 p-4" onSubmit={async (e) => {
          e.preventDefault();
          if (await act(() => api("/auth/password", { body: { current_password: pw.current, new_password: pw.next } }), [], t("settings.passwordChanged"))) setPw({ current: "", next: "" });
        }}>
          <input type="text" autoComplete="username" value={user?.email ?? ""} readOnly hidden />
          <Field label={t("settings.currentPassword")}><Input type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} /></Field>
          <Field label={t("settings.newPassword")}><Input type="password" autoComplete="new-password" minLength={12} value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} /></Field>
          <div><Button variant="primary" size="sm" type="submit" disabled={!pw.current || pw.next.length < 12}>{t("common.save")}</Button></div>
        </form>
      </Card>
      <Card>
        <CardHeader title={t("settings.twoFactor")} actions={<Badge tone={user?.totp_enabled ? "success" : "warning"}>{user?.totp_enabled ? t("settings.twoFactorEnabled") : t("settings.twoFactorDisabled")}</Badge>} />
        <div className="grid gap-3 p-4">
          {!user?.totp_enabled && !totp ? <div><Button size="sm" variant="primary" onClick={async () => setTotp((await act(() => api("/auth/totp/setup", { body: {} }), [], "")) as { secret: string; qr_svg: string } | null)}>{t("settings.enable2fa")}</Button></div> : null}
          {totp ? (
            <>
              <p className="text-[13px] text-muted">{t("settings.scanQr")}</p>
              {/* QR SVG is generated server-side by segno from our own data (no external content). */}
              <div className="w-44 rounded-md border border-border bg-white p-2" dangerouslySetInnerHTML={{ __html: totp.qr_svg }} />
              <p className="num text-[12px]">{t("settings.secret")}: {totp.secret}</p>
              <div className="flex gap-2">
                <Input className="num w-36" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} placeholder="123456" />
                <Button size="sm" variant="primary" onClick={async () => {
                  const r = (await act(() => api("/auth/totp/enable", { body: { code } }), [], "")) as { recovery_codes: string[] } | null;
                  if (r) { setCodes(r.recovery_codes); setTotp(null); qc.invalidateQueries({ queryKey: ["auth"] }); }
                }}>{t("auth.verify")}</Button>
              </div>
            </>
          ) : null}
          {user?.totp_enabled ? (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => setDisable({ ...disable, open: true })}>{t("settings.disable2fa")}</Button>
            </div>
          ) : null}
        </div>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader title={t("settings.sessions")} actions={<Button size="sm" variant="danger" onClick={async () => { await act(() => api("/auth/logout-all", { body: {} }), [], ""); window.location.href = "/login"; }}>{t("settings.logoutAll")}</Button>} />
        <ul className="divide-y divide-border">
          {sessions?.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-[13px]">
              <span className="num w-32">{s.ip || "—"}</span>
              <span className="min-w-0 flex-1 truncate text-[12px] text-muted">{s.user_agent}</span>
              <DateText value={s.last_seen_at} withTime />
              {s.current ? <Badge tone="accent">{t("settings.thisDevice")}</Badge> : <Button size="sm" variant="ghost" onClick={() => act(() => api(`/auth/sessions/${s.id}`, { method: "DELETE" }), ["sessions"])}>{t("settings.revoke")}</Button>}
            </li>
          ))}
        </ul>
      </Card>
      <Dialog open={codes !== null} onOpenChange={(v) => !v && setCodes(null)} title={t("settings.recoveryCodes")} description={t("settings.recoveryHint")}>
        <ul className="num grid grid-cols-2 gap-1 text-[13px]">{codes?.map((c) => <li key={c}>{c}</li>)}</ul>
      </Dialog>
      <Dialog open={disable.open} onOpenChange={(v) => setDisable({ ...disable, open: v })} title={t("settings.disable2fa")}
        footer={<><Button onClick={() => setDisable({ open: false, password: "", code: "" })}>{t("common.cancel")}</Button><Button variant="danger" onClick={async () => {
          if (await act(() => api("/auth/totp/disable", { body: { password: disable.password, code: disable.code } }))) { setDisable({ open: false, password: "", code: "" }); qc.invalidateQueries({ queryKey: ["auth"] }); }
        }}>{t("common.confirm")}</Button></>}>
        <div className="grid gap-3">
          <Field label={t("auth.password")}><Input type="password" autoComplete="current-password" value={disable.password} onChange={(e) => setDisable({ ...disable, password: e.target.value })} /></Field>
          <Field label={t("auth.code")}><Input className="num" value={disable.code} onChange={(e) => setDisable({ ...disable, code: e.target.value })} /></Field>
        </div>
      </Dialog>
    </div>
  );
}

interface Profile {
  id: string; key: string; name_en: string; name_tr: string; is_default: boolean; category_limits: Record<string, number>; thresholds: Record<string, number>;
  confidence_weights: Record<string, number>; min_confidence_for_high_priority: number; version: number;
  rules: { id: string; key: string; kind: string; category: string | null; signal: string; points: number; exclusive_group: string | null; title_en: string; title_tr: string; enabled: boolean; version: number }[];
}

/** Editable number group. "Save" is enabled only when a value differs from the stored one,
 * so saving never creates a new profile version without a real change. */
function NumMap({ label, info, value, onSave, showTotal }: { label: string; info?: string; value: Record<string, number>; onSave: (v: Record<string, number>) => Promise<unknown>; showTotal?: boolean }) {
  const t = useTranslations();
  const [draft, setDraft] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(value).map(([k, v]) => [k, String(v)])));
  const parsed = Object.fromEntries(Object.keys(value).map((k) => [k, Number(draft[k])]));
  const valid = Object.keys(value).every((k) => draft[k] !== "" && Number.isFinite(Number(draft[k])));
  const dirty = Object.keys(value).some((k) => Number(draft[k]) !== value[k] || draft[k] === "");
  const total = Object.values(parsed).reduce((a, b) => a + (Number.isFinite(b) ? b : 0), 0);
  return (
    <Card className="p-3">
      <p className="mb-2 flex items-center gap-1 text-[12px] font-medium text-muted">{label}{info ? <InfoTip>{info}</InfoTip> : null}</p>
      <form className="grid gap-2" onSubmit={async (e) => {
        e.preventDefault();
        if (dirty && valid) await onSave(parsed);
      }}>
        {Object.keys(value).map((k) => (
          <label key={k} className="grid grid-cols-[1fr_80px] items-center gap-2 text-[12px]">
            <span className="min-w-0">{t.has(`score.category.${k}`) ? t(`score.category.${k}`) : t.has(`score.components.${k}`) ? t(`score.components.${k}`) : t.has(`score.classification.${k}`) ? t(`score.classification.${k}`) : k}</span>
            <Input name={k} type="number" inputMode="numeric" className="num h-7" value={draft[k] ?? ""} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />
          </label>
        ))}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" type="submit" variant={dirty ? "primary" : "secondary"} disabled={!dirty || !valid}>{t("common.save")}</Button>
          {dirty ? (
            <>
              <Button size="sm" type="button" variant="ghost" onClick={() => setDraft(Object.fromEntries(Object.entries(value).map(([k, v]) => [k, String(v)])))}>{t("common.reset")}</Button>
              <span className="text-[11px] text-warning">{t("common.unsavedChanges")}</span>
            </>
          ) : <span className="text-[11px] text-muted">{t("common.noChanges")}</span>}
          {showTotal ? <span className={total > 100 ? "num ml-auto text-[11px] text-danger" : "num ml-auto text-[11px] text-muted"}>Σ {total}/100</span> : null}
        </div>
      </form>
    </Card>
  );
}

function ScoringTab() {
  const t = useTranslations();
  const locale = useLocale();
  const act = useAct();
  const { data: profiles } = useApi<Profile[]>(["scoring-profiles"], "/scoring/profiles");
  const { data: svc } = useApi<{ id: string; key: string; service: string; signal: string; requires_all: string[]; points: number; needs_review: boolean; enabled: boolean }[]>(["service-rules"], "/scoring/service-rules");
  const [sel, setSel] = useState<string>("");
  const [clone, setClone] = useState<{ key: string; name_en: string; name_tr: string } | null>(null);
  const p = profiles?.find((x) => x.id === sel) ?? profiles?.[0];
  if (!p) return null;
  const patchProfile = (body: Record<string, unknown>) => act(() => api(`/scoring/profiles/${p.id}`, { method: "PATCH", body }), ["scoring-profiles"]);
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <NativeSelect className="w-64" value={p.id} onChange={(e) => setSel(e.target.value)}>
          {profiles?.map((x) => <option key={x.id} value={x.id}>{locale === "tr" ? x.name_tr : x.name_en}{x.is_default ? " ★" : ""}</option>)}
        </NativeSelect>
        <Tooltip content={t("settings.versionInfo")}><span><Badge>v{p.version}</Badge></span></Tooltip>
        <Button size="sm" onClick={() => setClone({ key: `${p.key}_copy`, name_en: `${p.name_en} (copy)`, name_tr: `${p.name_tr} (kopya)` })}>{t("settings.clone")}</Button>
        <span className="ml-auto flex items-center gap-1">
          <Button size="sm" onClick={() => act(() => api("/scoring/recalculate-all", { body: {}, query: { profile_key: undefined } }), [], t("settings.recalcQueued"))}>{t("settings.recalcAll")}</Button>
          <InfoTip>{t("settings.recalcInfo")}</InfoTip>
        </span>
      </div>
      <Callout>{t("settings.scoringHelp")}</Callout>
      <div className="grid gap-3 md:grid-cols-3" key={p.id + p.version}>
        <NumMap label={t("settings.categoryLimits")} info={t("settings.categoryLimitsInfo")} showTotal value={p.category_limits} onSave={(v) => patchProfile({ category_limits: v })} />
        <NumMap label={t("settings.thresholds")} info={t("settings.thresholdsInfo")} value={p.thresholds} onSave={(v) => patchProfile({ thresholds: v })} />
        <NumMap label={t("settings.confidenceWeights")} info={t("settings.confidenceWeightsInfo")} value={p.confidence_weights} onSave={(v) => patchProfile({ confidence_weights: v })} />
      </div>
      <Card>
        <CardHeader title={<span className="flex items-center gap-1">{t("settings.rules")}<InfoTip>{t("settings.rulesInfo")}</InfoTip></span>} description={t("score.adsNote")} />
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead><tr className="border-b border-border text-left text-muted"><th className="px-4 py-2 font-medium">{t("common.name")}</th><th className="px-2 py-2 font-medium">{t("common.type")}</th><th className="px-2 py-2 font-medium">{t("settings.signal")}</th><th className="px-2 py-2 font-medium">{t("settings.group")}</th><th className="px-2 py-2 font-medium">{t("settings.points")}</th><th className="px-4 py-2 font-medium">{t("common.enabled")}</th></tr></thead>
            <tbody>
              {p.rules.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-1.5">{locale === "tr" ? r.title_tr : r.title_en}<span className="num ml-1 text-[10px] text-muted">v{r.version}</span></td>
                  <td className="px-2 py-1.5 text-muted">{r.category ? t(`score.category.${r.category}`) : r.kind}</td>
                  <td className="num px-2 py-1.5 text-muted">{r.signal}</td>
                  <td className="num px-2 py-1.5 text-muted">{r.exclusive_group ?? "—"}</td>
                  <td className="px-2 py-1.5">{r.kind === "exclusion" ? "—" : <Input type="number" className="num h-7 w-20" defaultValue={r.points} onBlur={(e) => Number(e.target.value) !== r.points && act(() => api(`/scoring/rules/${r.id}`, { method: "PATCH", body: { points: Number(e.target.value) } }), ["scoring-profiles"])} />}</td>
                  <td className="px-4 py-1.5"><Switch checked={r.enabled} label={r.key} onCheckedChange={(v) => act(() => api(`/scoring/rules/${r.id}`, { method: "PATCH", body: { enabled: v } }), ["scoring-profiles"])} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card>
        <CardHeader title={<span className="flex items-center gap-1">{t("settings.serviceRules")}<InfoTip>{t("settings.serviceRulesInfo")}</InfoTip></span>} />
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <tbody>
              {svc?.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-1.5">{t(`services.${r.service}`)}</td>
                  <td className="num px-2 py-1.5 text-muted">{r.signal}{r.requires_all.length ? ` + ${r.requires_all.join(" + ")}` : ""}</td>
                  <td className="px-2 py-1.5">{r.needs_review ? <Badge>review</Badge> : null}</td>
                  <td className="px-2 py-1.5"><Input type="number" className="num h-7 w-20" defaultValue={r.points} onBlur={(e) => Number(e.target.value) !== r.points && act(() => api(`/scoring/service-rules/${r.id}`, { method: "PATCH", body: { points: Number(e.target.value) } }), ["service-rules"])} /></td>
                  <td className="px-4 py-1.5"><Switch checked={r.enabled} label={r.key} onCheckedChange={(v) => act(() => api(`/scoring/service-rules/${r.id}`, { method: "PATCH", body: { enabled: v } }), ["service-rules"])} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Dialog open={clone !== null} onOpenChange={(v) => !v && setClone(null)} title={t("settings.clone")}
        footer={<><Button onClick={() => setClone(null)}>{t("common.cancel")}</Button><Button variant="primary" onClick={async () => { if (clone && await act(() => api(`/scoring/profiles/${p.id}/clone`, { body: clone }), ["scoring-profiles"])) setClone(null); }}>{t("common.create")}</Button></>}>
        {clone ? (
          <div className="grid gap-3">
            <Field label={t("dataSources.key")}><Input className="num" value={clone.key} onChange={(e) => setClone({ ...clone, key: e.target.value })} /></Field>
            <Field label={t("dataSources.nameEn")}><Input value={clone.name_en} onChange={(e) => setClone({ ...clone, name_en: e.target.value })} /></Field>
            <Field label={t("dataSources.nameTr")}><Input value={clone.name_tr} onChange={(e) => setClone({ ...clone, name_tr: e.target.value })} /></Field>
          </div>
        ) : null}
      </Dialog>
    </div>
  );
}

function CrmStatusesTab() {
  const t = useTranslations();
  const act = useAct();
  const { data } = useCrmStatuses();
  const name = useLocalizedName();
  const [add, setAdd] = useState({ name_en: "", name_tr: "" });
  const [remove, setRemove] = useState<{ key: string; label: string; count: number; moveTo: string } | null>(null);
  const keys = ["crm-statuses", "pipeline", "pipeline-table", "company-facets", "companies"];
  const save = (s: CrmStatusItem, patch: Partial<CrmStatusItem>) => {
    const next = { name_en: s.name_en, name_tr: s.name_tr, is_terminal: s.is_terminal, show_in_pipeline: s.show_in_pipeline, ...patch };
    if (!next.name_en.trim() || !next.name_tr.trim()) return;
    return act(() => api(`/crm/statuses/${s.key}`, { method: "PATCH", body: next }), keys);
  };
  const move = (i: number, dir: -1 | 1) => {
    if (!data) return;
    const order = data.map((s) => s.key);
    const j = i + dir;
    if (j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
    act(() => api("/crm/statuses/reorder", { body: { keys: order } }), keys, "");
  };
  return (
    <div className="grid gap-4">
      <Callout>{t("settings.crm.help")}</Callout>
      <Card>
        <CardHeader title={t("settings.tabs.crmStatuses")} />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-[13px]">
            <thead><tr className="border-b border-border text-left text-[12px] text-muted">
              <th className="w-16 px-4 py-2 font-medium">{t("settings.crm.order")}</th>
              <th className="px-2 py-2 font-medium">{t("tags.nameEn")}</th>
              <th className="px-2 py-2 font-medium">{t("tags.nameTr")}</th>
              <th className="px-2 py-2 font-medium"><span className="inline-flex items-center gap-1">{t("settings.crm.inPipeline")}<InfoTip>{t("settings.crm.inPipelineInfo")}</InfoTip></span></th>
              <th className="px-2 py-2 font-medium"><span className="inline-flex items-center gap-1">{t("settings.crm.closing")}<InfoTip>{t("settings.crm.closingInfo")}</InfoTip></span></th>
              <th className="px-2 py-2 text-right font-medium">{t("nav.companies")}</th>
              <th className="px-4 py-2" />
            </tr></thead>
            <tbody>
              {data?.map((s, i) => (
                <tr key={s.key} className="border-b border-border last:border-0">
                  <td className="px-4 py-1.5">
                    <span className="flex gap-0.5">
                      <Button size="icon-sm" variant="ghost" aria-label="up" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp /></Button>
                      <Button size="icon-sm" variant="ghost" aria-label="down" disabled={i === data.length - 1} onClick={() => move(i, 1)}><ArrowDown /></Button>
                    </span>
                  </td>
                  <td className="px-2 py-1.5"><Input className="h-7" defaultValue={s.name_en} maxLength={64} onBlur={(e) => e.target.value.trim() !== s.name_en && save(s, { name_en: e.target.value.trim() })} /></td>
                  <td className="px-2 py-1.5"><Input className="h-7" defaultValue={s.name_tr} maxLength={64} onBlur={(e) => e.target.value.trim() !== s.name_tr && save(s, { name_tr: e.target.value.trim() })} /></td>
                  <td className="px-2 py-1.5"><Switch checked={s.show_in_pipeline} label={t("settings.crm.inPipeline")} onCheckedChange={(v) => save(s, { show_in_pipeline: v })} /></td>
                  <td className="px-2 py-1.5"><Switch checked={s.is_terminal} label={t("settings.crm.closing")} onCheckedChange={(v) => save(s, { is_terminal: v })} /></td>
                  <td className="num px-2 py-1.5 text-right">{s.count}</td>
                  <td className="px-4 py-1.5 text-right">
                    {s.is_system ? (
                      <Tooltip content={t("settings.crm.systemInfo")}><span><Badge>{t("settings.crm.system")}</Badge></span></Tooltip>
                    ) : (
                      <Button size="icon-sm" variant="ghost" aria-label={t("common.delete")}
                        onClick={() => setRemove({ key: s.key, label: name(s), count: s.count, moveTo: data.find((x) => x.key !== s.key && x.key !== "do_not_contact")?.key ?? "new" })}><Trash2 /></Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <form className="flex flex-wrap items-end gap-2 border-t border-border p-4" onSubmit={async (e) => {
          e.preventDefault();
          if (await act(() => api("/crm/statuses", { body: { ...add, is_terminal: false, show_in_pipeline: true } }), keys)) setAdd({ name_en: "", name_tr: "" });
        }}>
          <Field label={t("tags.nameEn")} className="min-w-48 flex-1"><Input value={add.name_en} maxLength={64} onChange={(e) => setAdd({ ...add, name_en: e.target.value })} /></Field>
          <Field label={t("tags.nameTr")} className="min-w-48 flex-1"><Input value={add.name_tr} maxLength={64} onChange={(e) => setAdd({ ...add, name_tr: e.target.value })} /></Field>
          <Button type="submit" variant="primary" disabled={!add.name_en.trim() || !add.name_tr.trim()}><Plus />{t("settings.crm.add")}</Button>
        </form>
      </Card>
      <Dialog open={remove !== null} onOpenChange={(v) => !v && setRemove(null)} title={t("settings.crm.deleteTitle", { name: remove?.label ?? "" })}
        footer={<><Button onClick={() => setRemove(null)}>{t("common.cancel")}</Button><Button variant="danger" onClick={async () => {
          if (remove && await act(() => api(`/crm/statuses/${remove.key}`, { method: "DELETE", query: { move_to: remove.count ? remove.moveTo : undefined } }), keys)) setRemove(null);
        }}>{t("common.delete")}</Button></>}>
        {remove ? (remove.count ? (
          <Field label={t("settings.crm.moveCompanies", { count: remove.count })}>
            <NativeSelect value={remove.moveTo} onChange={(e) => setRemove({ ...remove, moveTo: e.target.value })}>
              {data?.filter((x) => x.key !== remove.key && x.key !== "do_not_contact").map((x) => <option key={x.key} value={x.key}>{name(x)}</option>)}
            </NativeSelect>
          </Field>
        ) : <p className="text-[13px] text-muted">{t("settings.crm.deleteEmpty")}</p>) : null}
      </Dialog>
    </div>
  );
}

function AuditRulesTab() {
  const t = useTranslations();
  const locale = useLocale();
  const act = useAct();
  const { data } = useApi<{ key: string; category: string; severity: string; title_en: string; title_tr: string; enabled: boolean; requires_browser: boolean; public_safe: boolean; version: number; emits_signals: string[] }[]>(["audit-rules"], "/audit-rules");
  return (
    <Card>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <tbody>
            {data?.map((r) => (
              <tr key={r.key} className="border-b border-border last:border-0">
                <td className="px-4 py-1.5"><p>{locale === "tr" ? r.title_tr : r.title_en}</p><p className="num text-[10px] text-muted">{r.key} · v{r.version}{r.emits_signals.length ? ` → ${r.emits_signals.join(", ")}` : ""}</p></td>
                <td className="px-2 py-1.5 text-muted">{t(`audit.categories.${r.category}`)}</td>
                <td className="px-2 py-1.5">
                  <NativeSelect className="h-7 w-28" value={r.severity} onChange={(e) => act(() => api(`/audit-rules/${r.key}`, { method: "PATCH", body: { severity: e.target.value } }), ["audit-rules"])}>
                    {["info", "low", "medium", "high", "critical"].map((s) => <option key={s} value={s}>{t(`audit.severity.${s}`)}</option>)}
                  </NativeSelect>
                </td>
                <td className="px-2 py-1.5">{r.requires_browser ? <Badge>browser</Badge> : null}</td>
                <td className="px-4 py-1.5"><Switch checked={r.enabled} label={r.key} onCheckedChange={(v) => act(() => api(`/audit-rules/${r.key}`, { method: "PATCH", body: { enabled: v } }), ["audit-rules"])} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ReviewTemplatesTab() {
  const t = useTranslations();
  const locale = useLocale();
  const act = useAct();
  const { data } = useApi<{ id: string; key: string; name_en: string; name_tr: string; is_default: boolean; questions: { id: string; key: string; text_en: string; text_tr: string; yes_signal: string | null; no_signal: string | null; enabled: boolean }[] }[]>(["review-templates"], "/review-templates");
  const [q, setQ] = useState<{ templateId: string; key: string; text_en: string; text_tr: string; yes_signal: string } | null>(null);
  return (
    <div className="grid gap-3">
      {data?.map((tpl) => (
        <Card key={tpl.id}>
          <CardHeader title={locale === "tr" ? tpl.name_tr : tpl.name_en} actions={<Button size="sm" onClick={() => setQ({ templateId: tpl.id, key: "", text_en: "", text_tr: "", yes_signal: "" })}><Plus />{t("common.add")}</Button>} />
          <ul className="divide-y divide-border">
            {tpl.questions.map((x) => (
              <li key={x.id} className="flex items-center gap-3 px-4 py-2 text-[13px]">
                <span className="flex-1">{locale === "tr" ? x.text_tr : x.text_en}</span>
                <span className="num text-[11px] text-muted">{x.yes_signal ?? "—"}</span>
                <Switch checked={x.enabled} label={x.key} onCheckedChange={(v) => act(() => api(`/review-questions/${x.id}`, { method: "PATCH", body: { ...x, enabled: v } }), ["review-templates"])} />
              </li>
            ))}
          </ul>
        </Card>
      ))}
      <Dialog open={q !== null} onOpenChange={(v) => !v && setQ(null)} title={t("review.questions")}
        footer={<><Button onClick={() => setQ(null)}>{t("common.cancel")}</Button><Button variant="primary" onClick={async () => {
          if (q && await act(() => api(`/review-templates/${q.templateId}/questions`, { body: { key: q.key, text_en: q.text_en, text_tr: q.text_tr, yes_signal: q.yes_signal || null } }), ["review-templates"])) setQ(null);
        }}>{t("common.save")}</Button></>}>
        {q ? (
          <div className="grid gap-3">
            <Field label={t("dataSources.key")}><Input className="num" value={q.key} onChange={(e) => setQ({ ...q, key: e.target.value })} /></Field>
            <Field label="English"><Input value={q.text_en} onChange={(e) => setQ({ ...q, text_en: e.target.value })} /></Field>
            <Field label="Türkçe"><Input value={q.text_tr} onChange={(e) => setQ({ ...q, text_tr: e.target.value })} /></Field>
            <Field label={`${t("settings.signal")} (yes)`}><Input className="num" placeholder="review.custom_signal" value={q.yes_signal} onChange={(e) => setQ({ ...q, yes_signal: e.target.value })} /></Field>
          </div>
        ) : null}
      </Dialog>
    </div>
  );
}

function ResourcesTab() {
  const t = useTranslations("settings");
  return (
    <div className="grid gap-4">
      <p className="text-[12px] text-muted">{t("resourcesHint")}</p>
      {([
        ["resources", ["limits.geofabrik_concurrency", "limits.heavy_concurrency", "limits.light_concurrency", "limits.max_pages_per_company", "limits.screenshots_per_site", "limits.min_free_disk_gb", "limits.max_screenshot_bytes", "limits.http_timeout_seconds", "limits.max_response_bytes", "limits.max_redirects", "limits.browser_timeout_seconds", "limits.max_memory_percent", "limits.max_cpu_percent", "limits.max_evidence_storage_mb"]],
        ["audit", ["audit.lighthouse_enabled", "audit.consent_tests_enabled", "audit.desktop_viewport", "audit.mobile_viewport", "audit.reuse_audit_days"]],
        ["discovery", ["geofabrik.base_url", "geofabrik.max_extract_bytes", "geofabrik.min_reimport_days"]],
        ["monitoring", ["monitoring.recheck_days", "monitoring.score_change_threshold", "monitoring.performance_change_threshold"]],
        ["security", ["security.session_ttl_hours", "security.idle_timeout_minutes", "security.login_max_attempts", "security.login_lockout_minutes"]],
      ] as const).map(([group, keys]) => (
        <Card key={group}>
          <CardHeader title={t(`groups.${group}`)} />
          <div className="p-4"><SettingsForm keys={[...keys]} /></div>
        </Card>
      ))}
    </div>
  );
}

function RetentionTab() {
  const t = useTranslations();
  const locale = useLocale();
  const act = useAct();
  const { data } = useApi<{ key: string; name_en: string; name_tr: string; retention_days: number | null; enabled: boolean }[]>(["retention"], "/retention-policies");
  return (
    <Card>
      <CardHeader title={t("settings.tabs.retention")} description={t("settings.retentionHint")} actions={<Button size="sm" onClick={() => act(() => api("/maintenance/retention", { body: {} }), [], t("settings.recalcQueued").split(" (")[0])}>{t("settings.runCleanup")}</Button>} />
      <ul className="divide-y divide-border">
        {data?.map((p) => (
          <li key={p.key} className="flex items-center gap-3 px-4 py-2 text-[13px]">
            <span className="flex-1">{locale === "tr" ? p.name_tr : p.name_en}</span>
            <Input type="number" min={0} className="num h-7 w-24" defaultValue={p.retention_days ?? ""} placeholder={t("settings.keepForever")} aria-label={t("settings.days")}
              onBlur={(e) => act(() => api(`/retention-policies/${p.key}`, { method: "PATCH", body: { retention_days: e.target.value === "" ? null : Number(e.target.value) } }), ["retention"])} />
            <span className="w-10 text-[12px] text-muted">{t("settings.days")}</span>
            <Switch checked={p.enabled} label={p.key} onCheckedChange={(v) => act(() => api(`/retention-policies/${p.key}`, { method: "PATCH", body: { enabled: v } }), ["retention"])} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

function SuppressionTab() {
  const t = useTranslations();
  const act = useAct();
  const [showRemoved, setShowRemoved] = useState(false);
  const { data } = useApi<{ id: string; kind: string; value: string; reason: string | null; created_at: string; removed_at: string | null; removal_reason: string | null; company_id: string | null }[]>(["suppression", showRemoved], `/suppression?include_removed=${showRemoved}`);
  const [add, setAdd] = useState({ kind: "domain", value: "", reason: "" });
  const [remove, setRemove] = useState<{ id: string; reason: string } | null>(null);
  return (
    <div className="grid gap-4">
      <p className="max-w-3xl text-[12px] text-muted">{t("settings.suppressionHint")}</p>
      <Card className="flex flex-wrap items-end gap-2 p-4">
        <Field label={t("settings.kind")}>
          <NativeSelect value={add.kind} onChange={(e) => setAdd({ ...add, kind: e.target.value })}>
            {["domain", "email", "phone", "company", "source"].map((k) => <option key={k} value={k}>{t(`settings.kinds.${k}`)}</option>)}
          </NativeSelect>
        </Field>
        <Field label={t("common.value")} className="min-w-56 flex-1"><Input value={add.value} onChange={(e) => setAdd({ ...add, value: e.target.value })} /></Field>
        <Field label={t("common.reason")} className="min-w-56 flex-1"><Input value={add.reason} onChange={(e) => setAdd({ ...add, reason: e.target.value })} /></Field>
        <Button variant="primary" disabled={!add.value} onClick={async () => { if (await act(() => api("/suppression", { body: { ...add, reason: add.reason || null } }), ["suppression"])) setAdd({ ...add, value: "", reason: "" }); }}><Plus />{t("settings.addSuppression")}</Button>
      </Card>
      <Card>
        <CardHeader title={t("settings.tabs.suppression")} actions={<label className="flex items-center gap-2 text-[12px] text-muted"><Checkbox label="removed" checked={showRemoved} onCheckedChange={setShowRemoved} />{t("settings.showRemoved")}</label>} />
        <ul className="divide-y divide-border">
          {data?.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-[13px]">
              <Badge>{t(`settings.kinds.${e.kind}`)}</Badge>
              <span className="num">{e.value}</span>
              <span className="flex-1 truncate text-[12px] text-muted">{e.reason}</span>
              <DateText value={e.created_at} />
              {e.removed_at ? <Badge tone="neutral">{e.removal_reason}</Badge> : <Button size="sm" variant="ghost" onClick={() => setRemove({ id: e.id, reason: "" })}>{t("settings.removeSuppression")}</Button>}
            </li>
          ))}
        </ul>
      </Card>
      <Dialog open={remove !== null} onOpenChange={(v) => !v && setRemove(null)} title={t("settings.removeSuppression")}
        footer={<><Button onClick={() => setRemove(null)}>{t("common.cancel")}</Button><Button variant="danger" disabled={(remove?.reason.length ?? 0) < 3} onClick={async () => {
          if (remove && await act(() => api(`/suppression/${remove.id}/remove`, { body: { reason: remove.reason } }), ["suppression"])) setRemove(null);
        }}>{t("common.confirm")}</Button></>}>
        <Field label={t("settings.removalReason")}><Input value={remove?.reason ?? ""} onChange={(e) => remove && setRemove({ ...remove, reason: e.target.value })} /></Field>
      </Dialog>
    </div>
  );
}

function ActivityTab() {
  const { data } = useApi<{ id: number; category: string; action: string; entity_type: string | null; entity_id: string | null; details: Record<string, unknown>; ip: string; created_at: string }[]>(["activity-log"], "/activity-log");
  return (
    <Card>
      <ul className="num divide-y divide-border text-[12px]">
        {data?.map((a) => (
          <li key={a.id} className="grid grid-cols-[150px_80px_160px_1fr_110px] gap-3 px-4 py-1.5">
            <DateText value={a.created_at} withTime /><span className="text-muted">{a.category}</span><span>{a.action}</span>
            <span className="truncate text-muted">{a.entity_type ? `${a.entity_type}:${a.entity_id}` : ""} {Object.keys(a.details).length ? JSON.stringify(a.details) : ""}</span>
            <span className="text-muted">{a.ip}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

interface Health {
  cpu_percent: number; cpu_count: number; memory: { total: number; used: number; percent: number }; disk: { total: number; free: number; used: number };
  database: { available: boolean; size_bytes: number; largest_tables: { table: string; bytes: number }[] };
  workers: { id: string; queues: string[]; last_seen_at: string; running_jobs: number; stats: Record<string, number> }[];
  pending_jobs: number; recent_errors: { id: string; name: string; error: string; at: string }[]; last_successful_import: string | null; last_successful_audit: string | null; note: string;
}

function HealthTab() {
  const t = useTranslations("settings.health");
  const locale = useLocale();
  const { data: h } = useApi<Health>(["health"], "/health/system", { refetchInterval: 15_000 });
  if (!h) return null;
  return (
    <div className="grid gap-4">
      <div className="grid gap-3 md:grid-cols-4">
        <Card className="p-4"><p className="text-[12px] text-muted">{t("cpu")}</p><p className="num text-[20px]">{h.cpu_percent}%</p><p className="text-[11px] text-muted">{h.cpu_count} vCPU</p></Card>
        <Card className="p-4"><p className="text-[12px] text-muted">{t("memory")}</p><p className="num text-[20px]">{h.memory.percent}%</p><Progress value={h.memory.used} total={h.memory.total} /></Card>
        <Card className="p-4"><p className="text-[12px] text-muted">{t("disk")}</p><p className="num text-[20px]">{fmtBytes(h.disk.free, locale)} <span className="text-[12px] text-muted">{t("free")}</span></p><Progress value={h.disk.used} total={h.disk.total} /></Card>
        <Card className="p-4"><p className="text-[12px] text-muted">{t("dbSize")}</p><p className="num text-[20px]">{fmtBytes(h.database.size_bytes, locale)}</p><p className="text-[11px] text-muted">{t("pending")}: {h.pending_jobs}</p></Card>
      </div>
      <p className="text-[11px] text-muted">{h.note}</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={t("workers")} />
          {!h.workers.length ? <p className="px-4 py-3 text-[12px] text-danger">{t("noWorkers")}</p> : null}
          <ul className="divide-y divide-border">{h.workers.map((w) => (
            <li key={w.id} className="flex items-center gap-3 px-4 py-2 text-[12px]"><span className="num">{w.id}</span><Badge>{w.queues.join(", ")}</Badge><span className="num text-muted">mem {w.stats.memory_percent ?? "—"}%</span><span className="ml-auto"><DateText value={w.last_seen_at} withTime /></span></li>
          ))}</ul>
        </Card>
        <Card>
          <CardHeader title={t("largestTables")} />
          <ul className="divide-y divide-border">{h.database.largest_tables.map((x) => <li key={x.table} className="flex justify-between px-4 py-1.5 text-[12px]"><span className="num">{x.table}</span><span className="num">{fmtBytes(x.bytes, locale)}</span></li>)}</ul>
        </Card>
        <Card>
          <CardHeader title={t("recentErrors")} />
          <ul className="divide-y divide-border">{h.recent_errors.map((e) => <li key={e.id} className="px-4 py-1.5 text-[12px]"><p>{e.name}</p><p className="truncate text-danger">{e.error}</p></li>)}</ul>
        </Card>
        <Card className="grid gap-2 p-4 text-[13px]">
          <p>{t("lastImport")}: <DateText value={h.last_successful_import} withTime /></p>
          <p>{t("lastAudit")}: <DateText value={h.last_successful_audit} withTime /></p>
        </Card>
      </div>
    </div>
  );
}

const TABS = ["general", "account", "scoring", "crmStatuses", "auditRules", "review", "resources", "retention", "suppression", "activity", "health"] as const;

function SettingsView() {
  const t = useTranslations("settings");
  const params = useSearchParams();
  const router = useRouter();
  const [tab, setTab] = useState<string>(params.get("tab") ?? "general");
  return (
    <>
      <PageHeader title={t("title")} />
      <Tabs value={tab} onValueChange={(v) => { setTab(v); router.replace(`/settings?tab=${v}`, { scroll: false }); }} tabs={TABS.map((v) => ({ value: v, label: t(`tabs.${v}`) }))} />
      <div className="mt-4">
        {tab === "general" ? <GeneralTab /> : null}
        {tab === "account" ? <AccountTab /> : null}
        {tab === "scoring" ? <ScoringTab /> : null}
        {tab === "crmStatuses" ? <CrmStatusesTab /> : null}
        {tab === "auditRules" ? <AuditRulesTab /> : null}
        {tab === "review" ? <ReviewTemplatesTab /> : null}
        {tab === "resources" ? <ResourcesTab /> : null}
        {tab === "retention" ? <RetentionTab /> : null}
        {tab === "suppression" ? <SuppressionTab /> : null}
        {tab === "activity" ? <ActivityTab /> : null}
        {tab === "health" ? <HealthTab /> : null}
      </div>
    </>
  );
}

export default function SettingsPage() {
  return <Suspense><SettingsView /></Suspense>;
}
