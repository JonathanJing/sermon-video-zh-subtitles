# Admin Workflow

Chinese version: [admin-workflow.zh.md](./admin-workflow.zh.md)

The Admin page is the operator surface for Sunday caption readiness. It is separate from the public congregation page so regular users only see captions, scripture, and readiness status.

## Route

- Public congregation page: `/`
- Admin page: `/admin` or `/admin.html`

The Admin page is operational and dense by design. The primary target devices are desktop and iPad. Mobile works for quick checks, but it is not the primary operator surface.

## What Operators Can Check

- Current Sunday slice.
- GCS bucket and prefix.
- Caption manifest status.
- Sermon title and translation status when a manifest is available.
- Secret presence as `configured`, `missing`, or `unknown`; raw keys and Secret Manager resource names are never displayed.
- Generation stage progress from source discovery through public page readiness.
- Observability evidence labels for `live_capture_triggered`, `worker_stage_completed`, `captions_ready`, page views, and unique-device estimates.

## Manual Trigger

The Admin page keeps the manual trigger flow available:

1. Enter a live/archive YouTube URL.
2. Optionally enter the approximate sermon start time, such as `00:23:25`.
3. Choose the Sunday slice.
4. Click `手动触发`.

The browser sends:

```json
{
  "triggerSource": "operator",
  "liveUrl": "https://www.youtube.com/watch?v=...",
  "sermonStart": "00:23:25"
}
```

to:

```text
POST /api/admin/sundays/YYYY-MM-DD/generate
```

The backend endpoint is protected by `OPERATOR_ADMIN_TOKEN` or `INTERNAL_TASK_TOKEN`. The current browser page does not expose or ask for those tokens. If the backend returns `401`, the Admin page clearly reports that the real trigger was blocked by auth and continues the local simulation for UI validation.

## Read-Only Status Endpoint

The Admin page reads:

```text
GET /api/admin/status
```

This endpoint returns safe runtime status only:

- bucket and prefix
- current Sunday
- timezone
- manifest summary
- caption summary
- provider label
- secret configured/missing state

It must not return raw API keys, operator tokens, Secret Manager resource names, cookies, or Authorization headers.

## Public Page Boundary

The public congregation page must remain simple:

- status pills
- sermon title/status
- disclaimer
- English transcript line
- Chinese caption line
- full transcript list
- scripture/sidebar content

It must not show source-discovery controls, manual trigger controls, export buttons, GCS settings, secret state, or operational logs.
