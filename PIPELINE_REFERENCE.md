# Pipeline YAML Reference

This document describes the YAML pipeline configuration format used to define watch items in Change Watcher.

---

## Structure Overview

A pipeline config has three top-level sections:

```yaml
shared_headers:   # Optional. Headers applied to every request.
auth:             # Optional. Multi-step authentication flow.
check:            # Required. The recurring monitoring request.
```

---

## `shared_headers`

Key-value pairs applied as HTTP headers to **all** requests (auth steps and check). Step-level headers override shared headers with the same key.

```yaml
shared_headers:
  User-Agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
  Accept: "application/json"
  Accept-Language: "en-US,en;q=0.9"
```

---

## `check` (required)

The recurring request that Change Watcher executes on your configured interval.

### Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `url` | Yes | — | Target URL. Supports `{{variables}}`. |
| `method` | No | `GET` | HTTP method: GET, POST, PUT, DELETE, PATCH, HEAD. |
| `headers` | No | `{}` | Request headers. Override `shared_headers`. |
| `body` | No | `""` | Request body. Supports `{{variables}}`. |
| `timeout` | No | `30` | Request timeout in seconds (1–120). |
| `selector_type` | Yes | — | How to parse the response: `css`, `jsonpath`, or `regex`. |
| `selector` | Yes | — | The selector expression to extract a value. |
| `reauth_on` | No | — | Conditions that trigger re-authentication. |

### `selector_type` options

- **`css`** — CSS selector applied to HTML. Extracts text content of the matched element.
  ```yaml
  selector_type: css
  selector: "h1.product-title"
  ```

- **`jsonpath`** — JSONPath expression applied to JSON response.
  ```yaml
  selector_type: jsonpath
  selector: "$.data.items[0].price"
  ```

- **`regex`** — Regular expression applied to the raw response body. Returns the first capture group if present, otherwise the full match.
  ```yaml
  selector_type: regex
  selector: "Price: \\$(\\d+\\.\\d{2})"
  ```

### `reauth_on`

Defines when to re-run the `auth` pipeline and retry the check.

| Field | Type | Description |
|-------|------|-------------|
| `status` | List of integers | Re-auth if check returns any of these HTTP status codes. |
| `selector_missing` | Boolean | Re-auth if the selector finds no match. |
| `max_retries` | Integer (>= 1) | Max re-auth attempts per check cycle. Default: `1`. |

```yaml
reauth_on:
  status: [401, 403]
  selector_missing: true
  max_retries: 1
```

**Flow when triggered:** clear variables → re-run all auth steps → retry check. If it still fails after `max_retries`, the item enters an error state and a notification is sent.

---

## `auth`

Optional section that defines a sequence of HTTP requests to obtain authentication tokens. Steps run in order. Each step can extract values from the response and make them available as `{{variables}}` in subsequent steps and in the `check` request.

### Auth step fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | Yes | — | Unique step name (for display and `next` references). |
| `url` | Yes | — | Request URL. Supports `{{variables}}`. |
| `method` | No | `GET` | HTTP method. |
| `headers` | No | `{}` | Step-level headers (override `shared_headers`). |
| `body` | No | `""` | Request body. Supports `{{variables}}`. |
| `timeout` | No | `30` | Request timeout in seconds (1–120). |
| `delay` | No | `0` | Seconds to wait **before** executing this step (0–60). Useful for skipping captcha popups or rate-limit windows. Accepts decimals (e.g. `0.5`). |
| `skip_if` | No | — | Variable name. Skip this step if the variable exists and is non-empty. |
| `on_status` | Yes | — | Status code handlers (see below). |

### `on_status`

Maps HTTP status codes to actions. Checked in this order:

1. **Exact match** — integer like `200`, `401`
2. **Wildcard** — pattern like `2xx`, `4xx`, `5xx`
3. **`default`** — catch-all fallback

Each handler can contain:

| Field | Description |
|-------|-------------|
| `extract` | List of extractions to pull variables from the response. |
| `action` | What to do: `fail` (stop pipeline with error) or `retry` (retry the step once). |
| `message` | Error message shown when `action: fail`. |
| `next` | Name of the next step to jump to (default: next in list). |

```yaml
on_status:
  200:
    extract:
      - name: "token"
        from: body
        jsonpath: "$.access_token"
  401:
    action: fail
    message: "Invalid credentials"
  default:
    action: fail
    message: "Unexpected response"
```

### Extractions

Each extraction pulls a value from the response and stores it as a named variable.

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Variable name to store the extracted value. |
| `from` | Yes | Source: `body`, `header`, `cookie`, or `status`. |
| `jsonpath` | Conditional | JSONPath expression (when `from: body`). |
| `css` | Conditional | CSS selector (when `from: body`). |
| `regex` | Conditional | Regex pattern (when `from: body` or `from: header`). |
| `key` | Conditional | Header name (when `from: header`) or cookie name (when `from: cookie`). |
| `transform` | No | List of transforms to apply to the extracted value. |

**Extraction source details:**

- **`from: body`** — Use with `jsonpath`, `css`, or `regex` to extract from the response body.
- **`from: header`** — Requires `key` (header name). Optionally add `regex` to extract a substring.
- **`from: cookie`** — Requires `key` (cookie name). Extracts from `Set-Cookie` header.
- **`from: status`** — Returns the HTTP status code as a string. No extraction method needed.

### Transforms

Optional pipeline of operations applied to an extracted value, in order.

| Transform | Argument | Description |
|-----------|----------|-------------|
| `strip` | — | Trim leading/trailing whitespace. |
| `lower` | — | Convert to lowercase. |
| `upper` | — | Convert to uppercase. |
| `prefix` | String | Prepend a string. |
| `suffix` | String | Append a string. |
| `regex` | Pattern | Extract using regex (first group or full match). |
| `replace` | `{old, new}` | Replace substring. |
| `base64_decode` | — | Decode base64. |
| `base64_encode` | — | Encode to base64. |
| `json_parse` | — | Parse string as JSON (for chaining with `jsonpath`). |
| `jsonpath` | Expression | Extract from JSON using JSONPath. |

```yaml
transform:
  - strip
  - prefix: "Bearer "
```

---

## Secrets

Secrets (passwords, API keys) are stored encrypted in the database. They are **never** written in the YAML itself. Instead, reference them with `{{secret_name}}` — the same syntax as pipeline variables.

Secrets are managed in the **Secrets** section of the edit form (above the YAML editor). They take the form of key-value pairs.

If a secret and a pipeline variable have the same name, the pipeline variable takes priority.

---

## Variables

Variables are values extracted during auth steps. They persist between check cycles so that auth doesn't re-run every time.

- Set by `extract` in auth step `on_status` handlers.
- Referenced as `{{variable_name}}` in `url`, `headers`, `body` fields.
- Cleared and re-populated when re-auth is triggered.
- Inspectable in the Pipeline Debugger in the UI.

---

## Examples

### 1. Simple HTML check (no auth)

Monitor a product price on a webpage.

```yaml
check:
  url: "https://store.example.com/product/12345"
  method: GET
  selector_type: css
  selector: "span.price"
```

### 2. Simple API check (no auth)

Monitor a cryptocurrency price from a public API.

```yaml
shared_headers:
  Accept: "application/json"

check:
  url: "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
  method: GET
  selector_type: jsonpath
  selector: "$.bitcoin.usd"
```

### 3. API check with regex

Extract a version number from a plain-text page.

```yaml
check:
  url: "https://example.com/releases/latest"
  method: GET
  selector_type: regex
  selector: "Version:\\s*(\\d+\\.\\d+\\.\\d+)"
```

### 4. POST request check

Monitor an API that requires a POST body.

```yaml
shared_headers:
  Content-Type: "application/json"
  Accept: "application/json"

check:
  url: "https://api.example.com/graphql"
  method: POST
  body: |
    {"query": "{ product(id: 123) { price } }"}
  selector_type: jsonpath
  selector: "$.data.product.price"
```

### 5. Single-step auth (login + check)

Login with username/password to get a token, then use it for checking.

**Secrets** (set in UI):
- `username` = `john@example.com`
- `password` = `s3cret`

```yaml
shared_headers:
  Content-Type: "application/json"
  Accept: "application/json"

auth:
  steps:
    - name: "Login"
      url: "https://api.example.com/auth/login"
      method: POST
      body: |
        {"email": "{{username}}", "password": "{{password}}"}
      on_status:
        200:
          extract:
            - name: "auth_token"
              from: body
              jsonpath: "$.token"
              transform:
                - prefix: "Bearer "
        401:
          action: fail
          message: "Invalid credentials"
        default:
          action: fail

check:
  url: "https://api.example.com/dashboard/stats"
  method: GET
  headers:
    Authorization: "{{auth_token}}"
  selector_type: jsonpath
  selector: "$.data.active_users"
  reauth_on:
    status: [401]
```

### 6. Multi-step auth (login + CSRF + session)

Some services require fetching a CSRF token first, then logging in with it.

**Secrets** (set in UI):
- `username` = `admin`
- `password` = `hunter2`

```yaml
shared_headers:
  User-Agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
  Accept: "text/html,application/json"

auth:
  steps:
    - name: "Get CSRF Token"
      url: "https://app.example.com/login"
      method: GET
      on_status:
        200:
          extract:
            - name: "csrf_token"
              from: body
              css: "input[name='_csrf']"
            - name: "session_id"
              from: cookie
              key: "JSESSIONID"
        default:
          action: fail

    - name: "Login"
      url: "https://app.example.com/login"
      method: POST
      delay: 3  # wait 3s after CSRF fetch to avoid captcha
      headers:
        Content-Type: "application/x-www-form-urlencoded"
        Cookie: "JSESSIONID={{session_id}}"
      body: "username={{username}}&password={{password}}&_csrf={{csrf_token}}"
      on_status:
        200:
          extract:
            - name: "auth_cookie"
              from: cookie
              key: "AUTH_TOKEN"
        302:
          extract:
            - name: "auth_cookie"
              from: cookie
              key: "AUTH_TOKEN"
        default:
          action: fail
          message: "Login failed"

check:
  url: "https://app.example.com/api/data"
  method: GET
  headers:
    Cookie: "AUTH_TOKEN={{auth_cookie}}"
  selector_type: jsonpath
  selector: "$.result.value"
  reauth_on:
    status: [401, 403]
    selector_missing: true
```

### 7. OAuth2 with refresh token

Login once to get access + refresh tokens. On subsequent checks, try the access token first. If expired, use the refresh token to get a new one without re-entering credentials.

**Secrets** (set in UI):
- `client_id` = `my-app-id`
- `client_secret` = `my-app-secret`
- `username` = `user@example.com`
- `password` = `p@ssw0rd`

```yaml
shared_headers:
  Content-Type: "application/json"
  Accept: "application/json"

auth:
  steps:
    - name: "Refresh Token"
      url: "https://auth.example.com/oauth/token"
      method: POST
      skip_if: "access_token"
      body: |
        {
          "grant_type": "refresh_token",
          "refresh_token": "{{refresh_token}}",
          "client_id": "{{client_id}}",
          "client_secret": "{{client_secret}}"
        }
      on_status:
        200:
          extract:
            - name: "access_token"
              from: body
              jsonpath: "$.access_token"
            - name: "refresh_token"
              from: body
              jsonpath: "$.refresh_token"
        default:
          next: "Full Login"

    - name: "Full Login"
      url: "https://auth.example.com/oauth/token"
      method: POST
      skip_if: "access_token"
      body: |
        {
          "grant_type": "password",
          "username": "{{username}}",
          "password": "{{password}}",
          "client_id": "{{client_id}}",
          "client_secret": "{{client_secret}}"
        }
      on_status:
        200:
          extract:
            - name: "access_token"
              from: body
              jsonpath: "$.access_token"
            - name: "refresh_token"
              from: body
              jsonpath: "$.refresh_token"
            - name: "token_type"
              from: body
              jsonpath: "$.token_type"
        default:
          action: fail
          message: "Authentication failed"

check:
  url: "https://api.example.com/v2/account/balance"
  method: GET
  headers:
    Authorization: "{{token_type}} {{access_token}}"
  selector_type: jsonpath
  selector: "$.balance"
  reauth_on:
    status: [401]
    max_retries: 2
```

**How this works:**

1. **First run:** No variables exist. `skip_if: "access_token"` is false for both steps, but "Refresh Token" fails (no `refresh_token` variable yet) and falls through to "Full Login" via `next: "Full Login"`. Full Login uses credentials to get both tokens.
2. **Subsequent runs:** `access_token` exists → both auth steps are skipped. The check runs directly with the stored token.
3. **Token expired:** Check returns 401 → `reauth_on` triggers. Variables are cleared. "Refresh Token" step runs (now `skip_if` is false since `access_token` was cleared), uses the stored `refresh_token` to get a new `access_token` without credentials.
4. **Refresh token also expired:** "Refresh Token" returns non-200 → falls through to "Full Login" which uses credentials for a complete re-auth.
5. **`max_retries: 2`** allows one retry with refresh + one retry with full login before giving up.

### 8. API key in header (no auth steps needed)

For APIs that use a static API key, just put it in a secret and reference it directly.

**Secrets** (set in UI):
- `api_key` = `sk-abc123def456`

```yaml
check:
  url: "https://api.example.com/v1/status"
  method: GET
  headers:
    X-API-Key: "{{api_key}}"
  selector_type: jsonpath
  selector: "$.system.health"
```

No `auth` section needed — the secret is substituted directly into the check headers.

### 9. Extract from response headers

Monitor a rate limit by reading a response header value.

```yaml
shared_headers:
  Authorization: "Bearer {{api_key}}"

auth:
  steps:
    - name: "Check Rate Limit"
      url: "https://api.example.com/v1/me"
      method: HEAD
      on_status:
        2xx:
          extract:
            - name: "rate_remaining"
              from: header
              key: "X-RateLimit-Remaining"

check:
  url: "https://api.example.com/v1/data"
  method: GET
  selector_type: jsonpath
  selector: "$.result"
```

### 10. Chained transforms

Extract a JWT payload from a token response.

```yaml
auth:
  steps:
    - name: "Get Token"
      url: "https://auth.example.com/token"
      method: POST
      headers:
        Content-Type: "application/json"
      body: |
        {"username": "{{username}}", "password": "{{password}}"}
      on_status:
        200:
          extract:
            - name: "jwt_token"
              from: body
              jsonpath: "$.token"
            - name: "user_id"
              from: body
              jsonpath: "$.token"
              transform:
                - regex: "^[^.]+\\.([^.]+)\\."
                - base64_decode
                - jsonpath: "$.sub"
        default:
          action: fail
```

This extracts the JWT, pulls the payload section via regex, decodes it from base64, then extracts the `sub` (subject/user ID) field from the decoded JSON.

### 11. Delay between auth steps (captcha avoidance)

Some sites trigger a captcha or rate-limit if requests come too fast after login page load. Use `delay` to pause before the next step.

**Secrets** (set in UI):
- `username` = `user@example.com`
- `password` = `p@ss`

```yaml
auth:
  steps:
    - name: "Load Login Page"
      url: "https://app.example.com/login"
      method: GET
      on_status:
        200:
          extract:
            - name: "csrf"
              from: body
              regex: 'name="csrf" value="([^"]+)"'

    - name: "Submit Login"
      url: "https://app.example.com/login"
      method: POST
      delay: 5  # wait 5 seconds to avoid captcha trigger
      headers:
        Content-Type: "application/x-www-form-urlencoded"
      body: "email={{username}}&pass={{password}}&csrf={{csrf}}"
      on_status:
        302:
          extract:
            - name: "session"
              from: cookie
              key: "sid"
        default:
          action: fail

    - name: "Get API Token"
      url: "https://app.example.com/api/token"
      method: GET
      delay: 2  # another short pause before token fetch
      headers:
        Cookie: "sid={{session}}"
      on_status:
        200:
          extract:
            - name: "api_token"
              from: body
              jsonpath: "$.token"
        default:
          action: fail

check:
  url: "https://app.example.com/api/data"
  method: GET
  headers:
    Authorization: "Bearer {{api_token}}"
  selector_type: jsonpath
  selector: "$.value"
  reauth_on:
    status: [401]
```

The `delay` field accepts decimals too — use `delay: 0.5` for a half-second pause.
