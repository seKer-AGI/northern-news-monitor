# n8n integration

n8n only **schedules and triggers** the collector. All Facebook access happens
inside Northern News Monitor through the configured authorized provider.

```text
Schedule Trigger (every 24h)
      ↓
HTTP Request  POST {API_URL}/api/v1/collection/run   (Authorization: Bearer <key>)
      ↓
IF  status == "success"
      ├─ true  → (optional) notify / fetch export
      └─ false → (optional) alert: partial_success or failed
```

## 1. Prerequisites

- The API is running (`python -m app serve` or `docker compose up -d`).
- `INTERNAL_API_KEY` is set in the API's `.env`.
- You know the URL n8n should use to reach the API:

| n8n runs… | API runs… | API URL |
|---|---|---|
| on the host | on the host / Docker with port 8000 published | `http://localhost:8000` |
| in Docker | on the host / published port | `http://host.docker.internal:8000` (on Linux, add `--add-host=host.docker.internal:host-gateway`) |
| in the same Docker network | compose service `api` | `http://api:8000` |
| n8n Cloud | a public server | `https://your-domain` (use HTTPS only) |

## 2. Credential (authentication)

In n8n, go to **Credentials → New → Header Auth**:

- **Name:** `Authorization`
- **Value:** `Bearer <INTERNAL_API_KEY>`

Save it as `Northern News Monitor API`. Don't paste the key directly into node
parameters, because it would then be visible in workflow exports.

## 3. Schedule Trigger node

- **Trigger Interval:** `Days`
- **Days Between Triggers:** `1`
- **Trigger at Hour:** e.g. `6am`
- **Trigger at Minute:** `0`

**Timezone:** the schedule uses the workflow timezone. Set it under
*Workflow → Settings → Timezone* (e.g. `Asia/Karachi`), or instance-wide with the
`GENERIC_TIMEZONE` environment variable. The collector itself works in UTC, so
the trigger time only decides *when* it runs. No posts are lost if a run is late
or skipped, because each source's window starts at its last successful
collection.

## 4. HTTP Request node

- **Method:** `POST`
- **URL:** `{API_URL}/api/v1/collection/run`
- **Authentication:** `Generic Credential Type` → `Header Auth` → select `Northern News Monitor API`
- **Send Body:** off. To limit the run to specific sources, turn it on and send
  JSON `{"source_ids": [1, 2]}`.
- **Options:**
  - **Timeout:** `600000` (10 min). The endpoint is synchronous, and 50 sources
    with retries can take several minutes.
  - **Response → Include Response Headers and Status:** on
  - **Response → Never Error:** on, so the IF node can inspect 409/502 bodies.
    Leave it off if you'd rather use n8n's Error Workflow for any non-2xx response.

Response codes:

| HTTP | Body `status` | Meaning |
|---|---|---|
| 200 | `success` | All sources collected |
| 200 | `partial_success` | Some sources failed. See `sources[].error_code` |
| 502 | `failed` | Every source failed (e.g. expired token) |
| 409 | – | A run is already in progress |
| 401 / 503 | – | Wrong key, or `INTERNAL_API_KEY` not configured |

## 5. IF node

With "Include Response Headers and Status" enabled, the response is under `body`:

- **Value 1:** `{{ $json.body.status }}`
- **Operation:** `is equal to`
- **Value 2:** `success`

## 6. Optional notification / export

- **True branch:** add an HTTP Request `GET {API_URL}/api/v1/export/json?start_date={{ $today.minus({days: 1}).toISODate() }}`
  with the same credential to pull yesterday's texts into Sheets, Slack, and so on.
- **False branch:** send an alert (Email, Slack, Telegram) containing
  `{{ $json.body.error_message }}` and `{{ JSON.stringify($json.body.sources) }}`.

## 7. Importable workflow

[`n8n-workflow.json`](n8n-workflow.json) contains the Schedule → HTTP Request →
IF chain. To use it:

1. In n8n, go to **Workflows → Import from File**.
2. Open the *Run collection* node, select your Header Auth credential, and set the URL.
3. Set the workflow timezone and activate the workflow.

The file was written for n8n 1.x node versions. If your n8n version shows
warnings on import, re-select the options listed above. The node settings on this
page are what matter.

## Alternative: Execute Command

If n8n runs on the same machine as the project, an **Execute Command** node can
run `python -m app collect` directly. Exit codes are `0` success, `3` partial,
and `1` failed. The HTTP approach is recommended because it keeps n8n and the
collector independently deployable.
