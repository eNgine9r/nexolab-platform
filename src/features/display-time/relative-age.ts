/**
 * Human-readable age of the newest data point. Long outages must read as hours
 * or days ("16 дн тому"), never as five-digit minute counts.
 */
export function formatRelativeAge(ageMs: number): string {
  if (!Number.isFinite(ageMs) || ageMs < 1_000) return "щойно";
  if (ageMs < 60_000) return `${Math.floor(ageMs / 1_000)} с тому`;
  const minutes = Math.floor(ageMs / 60_000);
  if (minutes < 60) return `${minutes} хв тому`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    const rest = minutes % 60;
    return rest === 0 ? `${hours} год тому` : `${hours} год ${rest} хв тому`;
  }
  return `${Math.floor(hours / 24)} дн тому`;
}
