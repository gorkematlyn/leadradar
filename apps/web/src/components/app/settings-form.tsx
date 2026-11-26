"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/input";
import { Switch } from "@/components/ui/misc";
import { useApi, useErrorMessage } from "@/hooks/use-api";
import { api } from "@/lib/api";

export interface SettingMeta { value: unknown; kind: string; group: string; secret: boolean; min: number | null; max: number | null }
export type SettingsMap = Record<string, SettingMeta>;

export function useSettings() {
  return useApi<SettingsMap>(["settings"], "/settings");
}

/** Edits a subset of DB-backed application settings. */
export function SettingsForm({ keys, labels }: { keys: string[]; labels?: Record<string, string> }) {
  const t = useTranslations();
  const qc = useQueryClient();
  const err = useErrorMessage();
  const { data } = useSettings();
  const [values, setValues] = useState<Record<string, unknown>>({});
  useEffect(() => {
    if (data) setValues(Object.fromEntries(keys.filter((k) => data[k]).map((k) => [k, data[k].secret ? "" : data[k].value])));
  }, [data, keys]);
  if (!data) return null;
  const save = async () => {
    const payload: Record<string, unknown> = {};
    for (const k of keys) {
      const meta = data[k];
      if (!meta) continue;
      let v = values[k];
      if (meta.secret && !v) continue; // keep existing secret
      if (meta.kind === "list" || meta.kind === "hosts") v = String(v ?? "").split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
      if (meta.kind === "int" || meta.kind === "float") v = v === "" || v === null ? null : Number(v);
      if (meta.kind === "origin" && !v) v = null;
      payload[k] = v;
    }
    try {
      await api("/settings", { method: "PUT", body: { values: payload } });
      toast.success(t("common.saved"));
      qc.invalidateQueries({ queryKey: ["settings"] });
    } catch (e) {
      toast.error(err(e));
    }
  };
  return (
    <div className="grid gap-3">
      <div className="grid gap-3 sm:grid-cols-2">
        {keys.filter((k) => data[k]).map((k) => {
          const meta = data[k];
          const label = labels?.[k] ?? (t.has(`settings.keys.${k}`) ? t(`settings.keys.${k}`) : k);
          if (meta.kind === "bool") {
            return (
              <label key={k} className="flex items-center gap-2 text-[13px]">
                <Switch checked={Boolean(values[k])} onCheckedChange={(v) => setValues({ ...values, [k]: v })} label={label} />{label}
              </label>
            );
          }
          if (meta.kind === "list" || meta.kind === "hosts") {
            const v = values[k];
            return (
              <Field key={k} label={label} className="sm:col-span-2">
                <Textarea rows={3} className="num" value={Array.isArray(v) ? v.join("\n") : String(v ?? "")} onChange={(e) => setValues({ ...values, [k]: e.target.value })} />
              </Field>
            );
          }
          return (
            <Field key={k} label={label} hint={meta.secret && meta.value ? t("dataSources.apifyTokenSet") : meta.min !== null ? `${meta.min} – ${meta.max}` : undefined}>
              <Input
                type={meta.secret ? "password" : meta.kind === "int" || meta.kind === "float" ? "number" : "text"}
                className={meta.kind === "int" || meta.kind === "float" ? "num" : undefined}
                autoComplete="off"
                value={String(values[k] ?? "")}
                onChange={(e) => setValues({ ...values, [k]: e.target.value })}
              />
            </Field>
          );
        })}
      </div>
      <div><Button variant="primary" size="sm" onClick={save}>{t("common.save")}</Button></div>
    </div>
  );
}
