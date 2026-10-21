# Gmail setup

The toolkit reads your Gmail through **your own** Google OAuth client, on your machine. Nothing goes through anyone else's server. It reads; it never replies, forwards, labels, trashes or marks anything. The one thing it can send is the daily digest, to your own address.

**What it uses Gmail for**
- Mail you sent (applications, outreach to professors) and mail you received from employers and their applicant portals: it files what was applied, acknowledged, rejected, invited, offered, or asks you for documents.
- Job-alert mail (LinkedIn and the region's boards): every posting at your levels becomes an unscored row to be read in full.
- The daily digest: one e-mail to yourself.

**Scopes requested:** `gmail.readonly`, `gmail.compose` (so a draft can be created, never sent) and `gmail.send` (reachable only through `send_digest_email()`, which is hard-guarded to your own address). Nothing broader.

## One-time setup (about 10 minutes; you do the consent steps yourself)

1. Open https://console.cloud.google.com/ and create a project (or reuse one).
2. **APIs & Services, Library:** enable the **Gmail API**.
3. **OAuth consent screen:** User type **External**; add the three scopes above (or leave scopes empty and let the first run request them); add your own Google account as a **test user**.
4. **Credentials, Create credentials, OAuth client ID**, type **Desktop app**. Download the JSON and save it as `config/gmail_credentials.json` (the `config/` folder is git-ignored; never commit this).
5. Run `python scripts/gmail_client.py auth`. A browser window opens: sign in, consent. A refresh token is cached at `config/gmail_token.json` (also git-ignored). A non-interactive session cannot do this step.
6. Check: `python scripts/mail_sync.py run --dry`, then `python scripts/mail_sync.py status`.

## The 7-day expiry (important)

While the consent screen is in **Testing** mode Google expires the refresh token after 7 days (`invalid_grant`): the pipeline then reports "Gmail not read" (audit C28) until you run `python scripts/gmail_client.py auth` again. To stop it, set the consent screen's publishing status to
**In production**. A personal-use app that only you use needs no Google verification; you will see an "unverified app" warning once at consent, which you can accept for your own app.

## Personalising what it looks for

- `profile.mail.ignore_senders` / `ignore_recipients`: regular expressions for senders (a newsletter, a bank) and recipients (the landlord you wrote to) that are not job mail.
- `profile/mail_patterns.json`: wordings of rejection, acknowledgement, interview, offer and information requests in your language (`resources/mail_patterns.json` already has French, Spanish, Italian, Dutch and Portuguese).
- The region pack adds the alert senders of its boards; `profile.mail.alert_senders` adds yours.

## If you do not want Gmail

Skip this. The watches, intake, analysis and dashboard run without it; you mark roles as applied, interview or rejected yourself on the dashboard. The pipeline shows Gmail as "not set up" and the digest cannot be mailed (it is still written to `digests/`).

## Revoking access

https://myaccount.google.com/permissions, remove the app; delete `config/gmail_token.json`.
