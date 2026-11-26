"use client";

import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { api, ApiError, type ApiOptions } from "@/lib/api";

export function useApi<T>(key: QueryKey, path: string | null, opts?: ApiOptions & { refetchInterval?: number | false }) {
  const { refetchInterval, ...rest } = opts ?? {};
  return useQuery<T>({
    queryKey: key,
    queryFn: ({ signal }) => api<T>(path as string, { ...rest, signal }),
    enabled: path !== null,
    refetchInterval,
  });
}

export function useErrorMessage() {
  const t = useTranslations();
  return (err: unknown) => {
    if (err instanceof ApiError) {
      const key = `errors.${err.detail}`;
      if (t.has(key)) return t(key);
      if (err.status === 429) return t("auth.tooMany");
    }
    return t("common.errorGeneric");
  };
}

export function useAction<TBody = unknown, TResult = unknown>(
  fn: (body: TBody) => Promise<TResult>,
  { invalidate = [], success }: { invalidate?: QueryKey[]; success?: string | ((r: TResult) => string | undefined) } = {},
) {
  const qc = useQueryClient();
  const message = useErrorMessage();
  return useMutation<TResult, unknown, TBody>({
    mutationFn: fn,
    onSuccess: (r) => {
      invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k }));
      const msg = typeof success === "function" ? success(r) : success;
      if (msg) toast.success(msg);
    },
    onError: (e) => toast.error(message(e)),
  });
}
