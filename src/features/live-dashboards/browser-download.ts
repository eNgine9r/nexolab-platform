const BLOB_URL_REVOKE_DELAY_MS = 1_000;

export interface BrowserBlobDownload {
  blob: Blob;
  filename: string;
}

/**
 * Hand an already-authenticated Blob to the browser download manager.
 *
 * Keep the object URL alive briefly after the synthetic click. Chromium may
 * commit the download asynchronously, so synchronously revoking the URL can
 * invalidate the handoff before the browser observes it.
 */
export function triggerBrowserBlobDownload(download: BrowserBlobDownload): void {
  const url = URL.createObjectURL(download.blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = download.filename;
  anchor.hidden = true;
  document.body.appendChild(anchor);

  try {
    anchor.click();
  } finally {
    anchor.remove();
    globalThis.setTimeout(() => URL.revokeObjectURL(url), BLOB_URL_REVOKE_DELAY_MS);
  }
}
