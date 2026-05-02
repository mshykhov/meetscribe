# Web history dashboard

A local-only browser UI for searching meeting history.

## Start

```bash
meetscribe web
# Open http://127.0.0.1:8123/ in your browser. Ctrl+C to stop.
```

Custom port: `meetscribe web --port 9000`.

## What it does

- Search videos by filename substring (matches against video path and output `.md` path).
- Filter by state (done / failed / invalid / cancelled / queued / processing).
- Filter by date range.
- Click "open" to view the summary `.md`.

## What it doesn't do

- Drag-and-drop upload - drop video files into `WATCH_DIR` via Finder.
- Live progress - SwiftBar plugin updates the menu bar in real time.
- Inline summary editing - open the `.md` in any editor.
- Cross-device access - binds to `127.0.0.1` only.
- Auto-start - server runs only while `meetscribe web` is in the foreground.

## Notes

- The `file://` link to the summary opens in a new tab. Chrome may block it
  silently when navigating from `http://`; in that case copy the path from
  the row and open it in Finder. Safari and Firefox usually permit it.
- The dashboard is static (no live refresh). Type in the search box or
  reload the page to refetch.
- `output_path` values that fall outside the configured `OUTPUT_DIR` are
  hidden from the UI as a sanity guard.
