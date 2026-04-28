# MedCRM SSO Flutter Integration

This guide is for the Flutter app that opens MedCRM in a WebView.

## Goal

The Flutter app asks Django for a one-time MedCRM SSO URL, then opens that URL in a WebView.

## Django Endpoint

```text
POST /api/integration/medcrm/webview-url/
Authorization: Bearer <django_access_token>
Content-Type: application/json
```

Request:

```json
{
  "next": "/dashboard"
}
```

`next` is optional. If provided, it must start with `/`.

Valid:

```text
/login
/dashboard
/patients
```

Invalid:

```text
login
https://example.com
//example.com
```

Success response:

```json
{
  "url": "https://crm.pediatr.kg/sso?token=...&next=%2Fdashboard"
}
```

## Flutter Flow

1. User taps "Open MedCRM".
2. Flutter calls Django `/api/integration/medcrm/webview-url/`.
3. Flutter receives `url`.
4. Flutter opens `url` in WebView.
5. MedCRM frontend completes Supabase login.

## Example Dart Code

```dart
import 'dart:convert';

import 'package:http/http.dart' as http;

Future<String> getMedcrmWebViewUrl({
  required String apiBaseUrl,
  required String djangoAccessToken,
  String next = '/dashboard',
}) async {
  final response = await http.post(
    Uri.parse('$apiBaseUrl/api/integration/medcrm/webview-url/'),
    headers: {
      'Authorization': 'Bearer $djangoAccessToken',
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: jsonEncode({
      'next': next,
    }),
  );

  final body = jsonDecode(response.body) as Map<String, dynamic>;

  if (response.statusCode != 200) {
    throw Exception(body['detail'] ?? body.toString());
  }

  final url = body['url'] as String?;
  if (url == null || url.isEmpty) {
    throw Exception('MedCRM SSO URL was not returned');
  }

  return url;
}
```

## Opening WebView

Use your existing WebView package. The important part is to open the exact URL returned by Django.

Pseudo-flow:

```dart
final url = await getMedcrmWebViewUrl(
  apiBaseUrl: 'https://profichat.operator.kg',
  djangoAccessToken: accessToken,
  next: '/dashboard',
);

openWebView(url);
```

## Error Handling

Handle these cases in Flutter:

- `401`: Django access token is missing/expired. Refresh token or ask user to log in again.
- `400`: invalid `next` or current user has no `phone_number`.
- `500`: Django SSO settings are missing on backend.

Show a user-friendly message:

```text
Не удалось открыть MedCRM. Попробуйте еще раз.
```

## Important Notes

- Do not parse or store the SSO token in Flutter.
- Do not reuse old URLs.
- Always request a fresh URL before opening WebView.
- The returned URL is valid for about 120 seconds and only once.
- Send `next` as `/login`, `/dashboard`, etc. Never send `login` without `/`.

## Quick Manual Test

1. Login in Flutter and get a valid Django access token.
2. Call:

```text
POST /api/integration/medcrm/webview-url/
```

3. Confirm response contains:

```text
https://crm.pediatr.kg/sso?token=...
```

4. Open that URL in WebView.
5. MedCRM should complete login automatically.
