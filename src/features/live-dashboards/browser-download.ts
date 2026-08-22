const BLOB_URL_REVOKE_DELAY_MS = 1_000;

export interface BrowserBlobDownload {
  blob: Blob;
  filename: string;
}

interface BrowserDownloadEnvironment {
  document: Document;
  createObjectURL: (blob: Blob) => string;
  revokeObjectURL: (url: string) => void;
  scheduleRevoke: (callback: () => void, delayMs: number) => void;
}

function browserDownloadEnvironment(): BrowserDownloadEnvironment {
  return {
    document,
    createObjectURL: (blob) => URL.createObjectURL(blob),
    revokeObjectURL: (url) => URL.revokeObjectURL(url),
    scheduleRevoke: (callback, delayMs) => {
      globalThis.setTimeout(callback, delayMs);
    },
  };
}

/**
 * Hand an already-authenticated Blob to the browser download manager.
 *
 * Keep the object URL alive briefly after the synthetic click. Chromium may
 * commit the download asynchronously, so synchronously revoking the URL can
 * invalidate the handoff before the browser observes it.
 */
export function triggerBrowserBlobDownload(
  download: BrowserBlobDownload,
  environment = browserDownloadEnvironment(),
): void {
  const url = environment.createObjectURL(download.blob);
  const anchor = environment.document.createElement("a");
  anchor.href = url;
  anchor.download = download.filename;
  anchor.hidden = true;
  environment.document.body.appendChild(anchor);

  try {
    anchor.click();
  } finally {
    anchor.remove();
    environment.scheduleRevoke(() => environment.revokeObjectURL(url), BLOB_URL_REVOKE_DELAY_MS);
  }
}
