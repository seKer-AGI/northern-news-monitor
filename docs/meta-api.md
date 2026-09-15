# Meta Graph API provider

This page covers what the official provider does, what Meta requires, and how to
connect a real account. Meta changes permissions and endpoints regularly, so
**check everything below against the current Meta documentation** before relying
on it:

- Graph API changelog: https://developers.facebook.com/docs/graph-api/changelog
- Page feed / posts reference: https://developers.facebook.com/docs/graph-api/reference/page/feed/
- Error handling: https://developers.facebook.com/docs/graph-api/guides/error-handling
- Access tokens: https://developers.facebook.com/docs/facebook-login/guides/access-tokens
- Securing requests (`appsecret_proof`): https://developers.facebook.com/docs/graph-api/securing-requests

## What the provider calls

Only documented functionality is used:

| Purpose | Request |
|---|---|
| Fetch posts | `GET /{version}/{page-id}/posts?fields=id,message,created_time&since=<unix>&until=<unix>&limit=100` |
| Next page | `paging.next` cursor. The provider re-applies its own token, and only on `graph.facebook.com` |
| Validate source | `GET /{version}/{page-id}?fields=id,name` |
| Health check | `GET /{version}/me?fields=id,name` |
| Request signing | `appsecret_proof = HMAC-SHA256(app_secret, access_token)`, sent when `META_APP_SECRET` is set |

`message` is the post text. Posts without `message` (photo- or video-only) are
skipped. No media, comments, reactions, or author fields are requested.

## Is it free? Am I eligible?

- There's no subscription fee for the Graph API. You create a Meta developer
  app, and access is controlled by permissions, features, App Review, and rate
  limits.
- Anyone can create a developer app at https://developers.facebook.com/apps.
  Creating an app **does not** give access to other people's content.

| Source | Requirement | Notes |
|---|---|---|
| Page **you manage** | Page access token with `pages_read_engagement` + `pages_read_user_content` | The simplest case. Works for people with a role on the app and the Page |
| Public Page you **don't** manage | *Page Public Content Access* (PPCA) feature | Requires App Review and a use case Meta approves. Approval isn't guaranteed |
| Facebook Group | Not available | Groups API deprecated in v19.0 (January 2024) and removed from **all** versions on 2024-04-22. The provider returns `SOURCE_NOT_SUPPORTED` without making a request |

## Step-by-step: connect a Page you manage

1. **Create an app.** Go to https://developers.facebook.com/apps → *Create app*.
   Pick the use case that includes managing Pages (the wording changes over time).
2. **Add permissions.** In the app's use-case or permissions settings, add
   `pages_show_list`, `pages_read_engagement`, and `pages_read_user_content`.
3. **Get a user token.** Open the Graph API Explorer
   (https://developers.facebook.com/tools/explorer/), select your app, request
   the permissions above, and click *Generate Access Token*.
4. **Get the Page token.** In the Explorer, run `GET /me/accounts`. Copy the
   `access_token` and `id` of your Page.
5. **Test it by hand**, before involving this project:
   ```
   GET /v25.0/<PAGE_ID>/posts?fields=id,message,created_time&limit=5
   ```
   If this fails in the Explorer, it will fail here too. Fix permissions first.
6. **Configure `.env`:**
   ```env
   DATA_PROVIDER=meta
   META_ACCESS_TOKEN=<page access token>
   META_API_VERSION=v25.0        # or the current version from the changelog
   META_APP_ID=<app id>
   META_APP_SECRET=<app secret>  # optional, enables appsecret_proof
   ```
7. **Verify:**
   ```bash
   python -m app provider health
   python -m app sources add --type page --name "My Page" --identifier <PAGE_ID>
   python -m app sources validate 1
   python -m app collect --source-id 1
   ```

## Tokens

Explorer tokens are short-lived (hours), which doesn't suit a daily job. Per
Meta's access-token documentation:

- A short-lived user token can be exchanged for a **long-lived user token**
  (about 60 days) using your app ID and secret.
- A Page token obtained with a long-lived user token (`GET /me/accounts`) is a
  long-lived Page token, which the docs describe as having no expiration date.
  It can still be invalidated, for example by a password change, removed
  permissions, or a lost Page role.
- For business setups, a **system user** token from Meta Business Settings is the
  recommended server-to-server credential.

When a token stops working, runs record `TOKEN_EXPIRED` for each affected
source. Watch `GET /api/v1/collection/runs?status=failed` or add an n8n alert.

## Error mapping

| Meta error | Provider code | Retried |
|---|---|---|
| code `190`, `102`, HTTP 401 | `TOKEN_EXPIRED` | no |
| code `4`, `17`, `32`, `613`, `80001`–`80014`, HTTP 429 | `RATE_LIMITED` | yes, bounded |
| code `10`, `200`–`299`, HTTP 403 | `PERMISSION_DENIED` | no |
| code `100` subcode `33`, code `803`, HTTP 404 | `INVALID_SOURCE` | no |
| code `1`, `2`, `is_transient`, HTTP 5xx, timeout/network | `PROVIDER_UNAVAILABLE` | yes, bounded |
| anything else | `PROVIDER_ERROR` | no |

## Known limitations

- **Groups are not supported** by the official API. Don't work around this. If
  you have a legitimately authorized group-data provider, implement
  `FacebookDataProvider` for it.
- The Page feed documentation mentions limits on how many posts can be read
  (for example, `limit` max 100 per request and caps on posts returned per
  year). For a 24-hour window this is rarely a problem.
  `META_MAX_PAGES` caps pagination per source and logs a warning if it's reached.
- Rate limits depend on your app, token type, and Page. Retries back off and
  give up. They don't try to avoid limits.
- The automated tests exercise the provider against documented Graph API
  response and error shapes via a fake HTTP transport
  (`tests/test_meta_provider.py`), **not** against a live Meta account. Do step 5
  above to confirm real access for your own app and token.
