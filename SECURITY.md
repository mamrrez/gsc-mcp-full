# Security policy

## What this server holds

When you sign in with Google, a **refresh token** is stored at
`~/.config/gsc-mcp-full/token.json` (owner-only permissions). It can read —
and, only if you set `GSC_ALLOW_WRITE=1`, change — the Search Console
properties your Google account can see, until you revoke it at
https://myaccount.google.com/permissions. The server runs on your machine;
the token is never sent anywhere except to Google.

The local history database (`history.sqlite`) contains the same data Search
Console shows you. Treat both files as private.

## Defaults that limit damage

- OAuth scope is `webmasters.readonly` unless you opt in to writing.
- Tools that change anything (add/remove property, submit/delete sitemap) refuse to run without `GSC_ALLOW_WRITE=1`.
- `history_sql` opens the database read-only.
- Query strings from the public are labelled as data in the server instructions; there is no tool that executes text from the data.

## Reporting a vulnerability

Please do **not** open a public issue. Email the maintainer (address on the
GitHub profile of [@mamrrez](https://github.com/mamrrez)) or use GitHub's
private vulnerability reporting on this repository. You will get a reply
within a week.

## Supply chain

Releases are built from tagged commits in this repository. Dependencies are
few and mainstream (`mcp`, `google-auth`, `google-auth-oauthlib`,
`requests`); language extras are optional and never installed by default.
