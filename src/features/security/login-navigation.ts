const LOCAL_ORIGIN = "http://nexolab.invalid";

export function safeLocalReturnTo(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.length > 2048 ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    /[\u0000-\u0020\u007f-\u009f]/.test(value)
  ) {
    return "/";
  }
  try {
    const url = new URL(value, LOCAL_ORIGIN);
    if (url.origin !== LOCAL_ORIGIN) return "/";
    let decodedPath = url.pathname;
    for (let depth = 0; depth < 3; depth++) {
      const next = decodeURIComponent(decodedPath);
      if (next === decodedPath) break;
      decodedPath = next;
    }
    if (
      !decodedPath.startsWith("/") ||
      decodedPath.startsWith("//") ||
      decodedPath.includes("\\") ||
      /[%?#\u0000-\u0020\u007f-\u009f]/.test(decodedPath)
    ) {
      return "/";
    }
    const normalizedPath = new URL(decodedPath, LOCAL_ORIGIN).pathname.replace(/\/+$/, "").toLowerCase();
    if (normalizedPath === "/login" || normalizedPath.startsWith("/login/")) return "/";
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return "/";
  }
}

export function localLoginHref(returnTo: unknown): string {
  const destination = safeLocalReturnTo(returnTo);
  return destination === "/" ? "/login" : `/login?returnTo=${encodeURIComponent(destination)}`;
}

export function replaceAfterLogin(
  returnTo: unknown,
  location: Pick<Location, "replace"> = window.location,
): void {
  location.replace(safeLocalReturnTo(returnTo));
}
