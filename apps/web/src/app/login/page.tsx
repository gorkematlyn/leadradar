"use client";

import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Card } from "@/components/ui/misc";
import { api, ApiError } from "@/lib/api";

interface State { setup_required: boolean; authenticated: boolean; mfa_pending: boolean }

function safeNext(value: string | null): string {
  // Only allow same-origin relative paths (prevents open redirects).
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return "/";
  return value;
}

function LoginForm() {
  const t = useTranslations("auth");
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [state, setState] = useState<State | null>(null);
  const [step, setStep] = useState<"password" | "mfa">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<State>("/auth/state").then((s) => {
      setState(s);
      if (s.authenticated) window.location.href = next;
      if (s.mfa_pending) setStep("mfa");
    });
  }, [next]);

  const errorText = (e: unknown) => {
    if (e instanceof ApiError) {
      if (e.detail === "account_locked") return t("locked");
      if (e.status === 429) return t("tooMany");
      if (e.detail === "invalid_code") return t("invalidCode");
    }
    return t("invalidCredentials");
  };

  const submitPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ mfa_required: boolean }>("/auth/login", { body: { email, password } });
      if (res.mfa_required) setStep("mfa");
      else window.location.href = next;
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const submitMfa = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/mfa", { body: recovery ? { recovery_code: code } : { code } });
      window.location.href = next;
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2">
          <span className="flex size-6 items-center justify-center rounded-[6px] bg-foreground"><span className="size-2 rounded-full bg-highlight" /></span>
          <span className="text-[15px] font-semibold tracking-tight">LeadRadar</span>
        </div>
        <Card className="p-5">
          {state?.setup_required ? (
            <div className="grid gap-3">
              <h1 className="text-[15px] font-semibold">{t("setupRequired")}</h1>
              <p className="text-[13px] text-muted">{t("setupHint")}</p>
              <pre className="num overflow-x-auto rounded-md border border-border bg-surface-2 p-2 text-[12px]">python -m leadradar.cli create-admin</pre>
            </div>
          ) : step === "password" ? (
            <form onSubmit={submitPassword} className="grid gap-3">
              <h1 className="text-[15px] font-semibold">{t("signInTitle")}</h1>
              <Field label={t("email")}>
                <Input type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
              </Field>
              <Field label={t("password")}>
                <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
              </Field>
              {error ? <p role="alert" className="text-[12px] text-danger">{error}</p> : null}
              <Button variant="primary" type="submit" disabled={busy}>{t("signIn")}</Button>
            </form>
          ) : (
            <form onSubmit={submitMfa} className="grid gap-3">
              <h1 className="text-[15px] font-semibold">{t("mfaTitle")}</h1>
              <p className="text-[13px] text-muted">{t("mfaHint")}</p>
              <Field label={recovery ? t("recoveryCode") : t("code")}>
                <Input
                  autoFocus
                  required
                  autoComplete="one-time-code"
                  inputMode={recovery ? "text" : "numeric"}
                  className="num tracking-widest"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
              </Field>
              {error ? <p role="alert" className="text-[12px] text-danger">{error}</p> : null}
              <Button variant="primary" type="submit" disabled={busy}>{t("verify")}</Button>
              <Button variant="link" size="sm" onClick={() => { setRecovery(!recovery); setCode(""); }}>
                {recovery ? t("useCode") : t("useRecovery")}
              </Button>
            </form>
          )}
        </Card>
        <p className="mt-4 text-[12px] text-muted">{t("privateNotice")}</p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
