"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

export interface AuthState {
  setup_required: boolean;
  authenticated: boolean;
  mfa_pending: boolean;
  user: User | null;
}

export function useSession() {
  return useQuery<AuthState>({ queryKey: ["auth"], queryFn: () => api<AuthState>("/auth/state"), staleTime: 60_000 });
}
