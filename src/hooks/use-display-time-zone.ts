"use client";

import { useSyncExternalStore } from "react";
import { getDisplayTimeZone, subscribeDisplayTimeZone } from "@/features/display-time/store";

const serverTimeZone = () => "UTC";

export function useDisplayTimeZone(): string {
  return useSyncExternalStore(subscribeDisplayTimeZone, getDisplayTimeZone, serverTimeZone);
}
