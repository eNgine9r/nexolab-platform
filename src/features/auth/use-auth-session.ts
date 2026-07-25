"use client";

import { useCallback, useEffect, useState } from "react";

import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

import {
  demoAuthSession,
  fetchAuthSession,
  readBrowserAccessToken,
  type AuthSession,
  type AuthSessionError,
} from "./auth-session";

export type AuthSessionState =
  | { status: "loading"; session: null; error: null; mode: "demo" | "live" }
  | { status: "authenticated"; session: AuthSession; error: null; mode: "demo" | "live" }
  | { status: "unauthenticated" | "error"; session: null; error: AuthSessionError; mode: "live" };

export function useAuthSession(): AuthSessionState & { reload: () => void } {
  const [epoch, setEpoch] = useState(0);
  const [state, setState] = useState<AuthSessionState>(() => {
    try {
      const runtime = getTelemetryRuntimeConfig();
      if (runtime.mode === "demo") {
        return {
          status: "authenticated",
          session: demoAuthSession(),
          error: null,
          mode: "demo",
        };
      }
      return { status: "loading", session: null, error: null, mode: "live" };
    } catch {
      return { status: "loading", session: null, error: null, mode: "live" };
    }
  });

  useEffect(() => {
    let active = true;
    let runtime: ReturnType<typeof getTelemetryRuntimeConfig>;
    try {
      runtime = getTelemetryRuntimeConfig();
    } catch {
      setState({
        status: "error",
        session: null,
        mode: "live",
        error: {
          code: "AUTH_REQUEST_FAILED",
          message: "Некоректна конфігурація live-режиму.",
          status: null,
          permission: null,
        },
      });
      return () => {
        active = false;
      };
    }

    if (runtime.mode === "demo") {
      setState({
        status: "authenticated",
        session: demoAuthSession(),
        error: null,
        mode: "demo",
      });
      return () => {
        active = false;
      };
    }

    const apiBaseUrl = runtime.apiBaseUrl;
    if (!apiBaseUrl) {
      setState({
        status: "error",
        session: null,
        mode: "live",
        error: {
          code: "AUTH_REQUEST_FAILED",
          message: "NEXOLAB API URL не налаштовано.",
          status: null,
          permission: null,
        },
      });
      return () => {
        active = false;
      };
    }

    setState({ status: "loading", session: null, error: null, mode: "live" });
    void fetchAuthSession(apiBaseUrl, readBrowserAccessToken()).then((result) => {
      if (!active) return;
      if (result.ok) {
        setState({
          status: "authenticated",
          session: result.value,
          error: null,
          mode: "live",
        });
        return;
      }
      setState({
        status: result.error.code === "AUTHENTICATION_REQUIRED" ? "unauthenticated" : "error",
        session: null,
        error: result.error,
        mode: "live",
      });
    });

    return () => {
      active = false;
    };
  }, [epoch]);

  const reload = useCallback(() => setEpoch((current) => current + 1), []);
  return { ...state, reload };
}
