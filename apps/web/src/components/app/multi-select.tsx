"use client";

import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/misc";
import { Popover } from "@/components/ui/overlay";
import { cn } from "@/lib/utils";

export interface Option {
  value: string;
  label: string;
  icon?: React.ReactNode;
  count?: number; // how many records have this value (shown on the right)
}

export function MultiSelect({ label, options, value, onChange, searchable, className }: {
  label: string; options: Option[]; value: string[]; onChange: (v: string[]) => void; searchable?: boolean; className?: string;
}) {
  const t = useTranslations("common");
  const [q, setQ] = useState("");
  const filtered = useMemo(
    () => (q ? options.filter((o) => o.label.toLowerCase().includes(q.toLowerCase()) || o.value.toLowerCase().includes(q.toLowerCase())) : options),
    [options, q],
  );
  const toggle = (v: string) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  return (
    <Popover
      trigger={
        <Button size="sm" className={cn("justify-between", className)}>
          <span className="truncate">{label}</span>
          {value.length ? <span className="num rounded-sm bg-surface-2 px-1 text-[11px]">{value.length}</span> : null}
          <ChevronDown className="text-muted" />
        </Button>
      }
      className="w-72 p-0"
    >
      {searchable ? (
        <div className="border-b border-border p-2">
          <Input placeholder={t("search")} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      ) : null}
      <div className="flex justify-between border-b border-border px-2 py-1">
        <Button size="sm" variant="ghost" onClick={() => onChange(Array.from(new Set([...value, ...filtered.map((o) => o.value)])))}>{t("selectAll")}</Button>
        <Button size="sm" variant="ghost" onClick={() => onChange([])}>{t("deselectAll")}</Button>
      </div>
      <ul className="max-h-72 overflow-y-auto p-1">
        {filtered.map((o) => (
          <li key={o.value}>
            <label className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-[13px] hover:bg-surface-2">
              <Checkbox label={o.label} checked={value.includes(o.value)} onCheckedChange={() => toggle(o.value)} />
              {o.icon}
              <span className="min-w-0 flex-1 truncate">{o.label}</span>
              {o.count !== undefined ? <span className="num shrink-0 text-[11px] text-muted">{o.count}</span> : null}
            </label>
          </li>
        ))}
        {!filtered.length ? <li className="px-2 py-3 text-center text-[12px] text-muted">{t("noResults")}</li> : null}
      </ul>
    </Popover>
  );
}
