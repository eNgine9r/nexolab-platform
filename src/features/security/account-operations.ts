"use client";
import { useSyncExternalStore } from "react";
let pending = 0;
const listeners = new Set<() => void>();
function emit() {
  for (const listener of listeners) listener();
}
export function isAccountOperationPending() {
  return pending > 0;
}
export function beginAccountOperation() {
  pending += 1;
  emit();
  let released = false;
  return () => {
    if (released) return;
    released = true;
    pending -= 1;
    emit();
  };
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function useAccountOperationPending() {
  return useSyncExternalStore(subscribe, isAccountOperationPending, () => false);
}
