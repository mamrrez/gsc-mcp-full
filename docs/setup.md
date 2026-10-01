---
title: 1 · Google credentials
nav_order: 2
description: Create the OAuth client (or service account) that lets the server read your Search Console data.
---

# Step 1 — Google credentials
{: .no_toc }

The server talks to Google's Search Console API on your behalf. Google needs to know *which app* is asking, so you create a free "OAuth client" in your own Google Cloud project once. Nothing is billed; the Search Console API has no cost.

{: .note }
Every user creates their own client. That is deliberate: your sign-in never goes through anyone else's app, and the project author never sees your data or your token.

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Option A — OAuth with your own Google account (recommended)

Use this when you are a person who signs in to Search Console in a browser.

### 1. Create a project

1. Open <https://console.cloud.google.com/> and sign in with the Google account that has access to your Search Console properties.
2. Click the project picker at the top → **New project** → name it (e.g. `search-console-mcp`) → **Create**. Select it when it is ready.

### 2. Enable the API

1. Left menu → **APIs & Services → Library**.
2. Search **Google Search Console API** → open it → **Enable**.

### 3. Configure the consent screen

1. **APIs & Services → OAuth consent screen** (in newer consoles this is under **Google Auth Platform → Branding / Audience**).
2. Audience: **External**. App name: anything (e.g. `Search Console MCP`). Add your email as support and developer contact. Save.
3. Under **Audience → Test users** add your own Google address.
4. **Publishing status:** while the app is in *Testing*, Google expires every sign-in after **7 days** and you will have to run `auth` again each week. To avoid that, click **Publish app** (status becomes *In production*). You do **not** need to complete verification for personal use — you will simply see a "Google hasn't verified this app" screen when signing in; click **Advanced → Go to … (unsafe)**. It is your own app, so it is safe.

### 4. Create the OAuth client

1. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type: **Desktop app**. Name it. **Create**.
3. **Download JSON**. Save it somewhere permanent, e.g. `~/.config/gsc-mcp-full/client_secret.json`. This is the file `GSC_CREDENTIALS_PATH` points at.

{: .warning }
The downloaded JSON identifies your app, not your account — but keep it private anyway, and never commit it to git. Your actual sign-in (the token) is created in Step 2 and stored separately.

That's it. Continue to [Install & connect](install).

---

## Option B — Service account (for servers, cron jobs, teams)

A service account is a robot identity: no browser, no expiry, works on a server. Use it for scheduled `sync` jobs or shared team setups.

1. In your Cloud project: **IAM & Admin → Service accounts → Create service account**. Name it, skip the optional role steps, **Done**.
2. Open the account → **Keys → Add key → Create new key → JSON**. The key file downloads. Point `GSC_CREDENTIALS_PATH` at it.
3. Copy the service account's email (`something@your-project.iam.gserviceaccount.com`).
4. In **Search Console** → your property → **Settings → Users and permissions → Add user** → paste that email → permission **Full** (or Restricted for read-only) → Add. Repeat for every property the server should see.

{: .note }
A service account sees only the properties you explicitly add it to. `list_properties` returning nothing almost always means this step was skipped.

## What the scopes mean

The server asks Google for `webmasters.readonly` by default — it can read reports and inspect URLs, nothing more. Only when you set `GSC_ALLOW_WRITE=1` does it ask for `webmasters`, which also allows adding/removing properties and submitting/deleting sitemaps. You can see and revoke either grant at <https://myaccount.google.com/permissions>.
