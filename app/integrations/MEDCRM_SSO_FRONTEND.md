# MedCRM SSO Frontend Integration

This guide is for the MedCRM web frontend at `https://crm.pediatr.kg`.

## Goal

Open `/sso?token=...&next=...`, exchange the one-time token through the Supabase Edge Function, then redirect the user to the Supabase magic link returned by the function.

## Required Backend Pieces

Supabase Edge Function:

```text
POST /functions/v1/sso-login
```

Request:

```json
{
  "token": "one-time-token-from-url"
}
```

Success response:

```json
{
  "action_link": "https://...",
  "account_type": "employee",
  "next": "/dashboard"
}
```

`account_type` can be:

```text
employee
patient
```

## `/sso` Page Behavior

1. Read `token` from the URL query string.
2. Optionally read `next`.
3. If `token` is missing, show an error page.
4. Call Supabase Edge Function `sso-login`.
5. If the response is successful, redirect to `action_link`.
6. If the response fails, show an error page.

## Example Implementation

```ts
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

async function runSsoLogin() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token");

  if (!token) {
    throw new Error("Missing SSO token");
  }

  const { data, error } = await supabase.functions.invoke("sso-login", {
    body: { token },
  });

  if (error) {
    throw new Error(error.message || "SSO login failed");
  }

  if (!data?.action_link) {
    throw new Error("SSO login failed: missing action_link");
  }

  window.location.href = data.action_link;
}

runSsoLogin().catch((error) => {
  console.error(error);
  // Render your normal error UI here.
});
```

## Important Notes

- The SSO token is one-time use.
- The SSO token expires after 120 seconds by default.
- Do not store the SSO token in localStorage.
- Do not send the token to any service except `sso-login`.
- The `next` value must be a relative path that starts with `/`, for example `/login` or `/dashboard`.

## Supabase Secrets

The production Supabase project must have:

```bash
supabase secrets set MAIN_DJANGO_API_URL="https://profichat.operator.kg"
supabase secrets set MAIN_DJANGO_INTEGRATION_SECRET="<same value as MEDCRM_SSO_INTEGRATION_SECRET in Django>"
supabase secrets set MEDCRM_AUTH_REDIRECT_URL="https://crm.pediatr.kg/auth/callback"
supabase secrets set MEDCRM_SSO_INTERNAL_EMAIL_DOMAIN="medcrm-sso.local"
```

## Acceptance Check

1. Open a fresh SSO URL:

```text
https://crm.pediatr.kg/sso?token=...&next=%2Fdashboard
```

2. The page calls `sso-login`.
3. `sso-login` returns `action_link`.
4. Browser redirects to `action_link`.
5. Supabase creates a session.
6. User lands inside MedCRM.
