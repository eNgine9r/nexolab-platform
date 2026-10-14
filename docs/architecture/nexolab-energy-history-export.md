# Energy historical export

Work Package1363 extends the accepted graph1362 without changing acquisition,
telemetry persistence, the existing history API or Saved Dashboard exports.
Production remains on its independently validated package until normal update
and rollback gates pass.

The authenticated Energy export API discovers saved canonical series only for
active nodes belonging to the selected organization. Known LE-01MP and SDM120
capabilities and native units restrict the catalog. Owner keys bind organization,
identity/provider/subject; opaque IDs do not grant access to another user's job.

Preview and rendering run in one dedicated spawned local process at a time.
The bounded queue and short database sessions keep scans and XLSX compression
outside the HTTP event loop and ingestion process. Original scalar observations
are frozen in a private SQLite staging file beneath a dedicated energy-exports
child of the configured ingestion-spool directory. No ingestion files are used
as staging or cleanup targets. Restart fails interrupted jobs explicitly; retained
prepared/ready files keep their owner and expiry. Only recognized private job
directories may be cleaned. At the manifest cap, oldest canceled/failed/expired
jobs are reclaimed once their worker has exited; active and prepared/ready jobs
remain protected. Capacity errors fail instead of truncating files.

A brief existing advisory synchronization establishes the received-at watermark;
it ends before counts or scans. Reads use captured-at/event-ID keyset pagination
with at most1000 records per page. Source counts are compared before, during and
after extraction to detect retention loss. Preview and download then read the
same immutable frozen dataset, independent of later retention or ingestion.

RAW rows combine only exactly equal measurement timestamps and meter identities.
Every value retains its channel, event ID and quality. Same-series timestamp
collisions occupy additional deterministic rows; asynchronous values are sparse.
Scalar source-event counts and wide output-row counts are separate quantities.

Buckets use elapsed UTC seconds from the selected start, with a clipped final
interval. Instantaneous avg/min/max use finite valid readings; empty values remain
blank with explicit quality and counts. Counter columns distinguish cumulative
EΣ and delta kWh. Actual floor-at-boundary readings are shared between adjacent
buckets; actual anchor timestamps and coverage remain visible. Invalid readings,
counter decreases, gaps or inadequate anchors invalidate delta. No reset/rollover
or power-integration estimate is substituted. A reading exactly at the period
end is an optional labeled counter anchor, never an in-period RAW observation.

Step availability is conservatively bounded by the largest observed positive
adjacent interval in every unreduced selected series. Sparse or unknown resolution
allows only RAW. Gaps can restrict steps; the interface explains that limitation.
Counter continuity separately considers observed gap evidence. Export options
never change physical polling, persistence or the graph point budget.

Europe/Kyiv is explicit regardless of browser timezone. UTC and local ISO strings
with offsets distinguish repeated hours. Nonexistent wall times are rejected;
ambiguous times require choosing an occurrence. XLSX has typed numeric measurements,
Metadata and numbered Data sheets before the Excel row limit. CSV is rectangular
UTF-8, comma-delimited, dot-decimal, quoted as needed, with metadata columns and
formula-safe text. Large downloads use fresh authenticated authorization and a
short-lived one-use artifact ticket, allowing streamed transfer without a browser
Blob holding the complete file.

Software acceptance uses isolated synthetic SQLite/PostgreSQL datasets and actual
browser/API flows. Raspberry Pi resource/ingestion-lag acceptance is tracked under
1364; it does not authorize production activation or hardware writes.
