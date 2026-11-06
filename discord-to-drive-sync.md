# Project: Discord → Google Drive auto-sync (free, no 24/7 server)

## 0. Instructions for the AI agent reading this

You are implementing this project for a university student. Read the whole file first.

- Create every file listed in section 5 exactly as specified (adjust only if you find a real bug).
- Some steps can only be done by the human (Discord developer portal, Google Cloud console, adding the bot to the server, GitHub secrets). Those are in section 4. **Stop and ask the human to do them, one block at a time**, and wait for confirmation. Do not invent credentials.
- Never print, log, or commit secrets (bot token, Google client secret, refresh token). `client_secret.json` must be in `.gitignore`.
- If the human has the `gh` CLI authenticated, you may create the repo and set secrets with it (`gh secret set NAME`). Otherwise, give them the exact manual clicks.
- Run the test plan in section 6 before declaring success.

---

## 1. Goal

A class representative posts course files (lectures, worksheets, corrections) in a Discord server. Each module has its own text channel. Goal: every attachment posted in a channel is automatically copied to Google Drive, into a folder named after that channel, so students can browse a clean Drive instead of scrolling Discord.

Requirements:
- Free, no PC or server left running.
- Works on the **existing** channels (no manual mapping). New channels get new folders automatically.
- Backfills the full existing history on the first runs.
- Never uploads the same file twice.
- Read-only on Discord (the bot never posts or modifies anything).

## 2. How it works (important: it is NOT a command-triggered bot)

There are two pieces:

1. **A Discord bot account.** It is only a "member" that the class rep adds to the server so the script is *allowed to read* the channels. It never runs, never listens, and has no slash commands.
2. **A Python script (`sync.py`)** that runs on **GitHub Actions on a timer** (cron). Each run it:
   1. lists the server's text channels,
   2. for each channel, fetches messages newer than the last processed message ID,
   3. downloads each attachment,
   4. uploads it to Drive in `Discord Courses/<channel-name>/`,
   5. saves the new "last processed message ID" per channel in `state.json`, which the workflow commits back to the repo.

Trigger = schedule (every 30 min) or the manual "Run workflow" button. There are no slash commands. Adding slash commands would require a bot online 24/7, which defeats the free/no-hosting goal.

## 3. Key design decisions (and why)

| Decision | Reason |
|---|---|
| GitHub Actions cron instead of a hosted bot | Free, no server, no sleeping free-tier hosts |
| Discord REST API with `requests`, not `discord.py` | No persistent connection needed |
| Google **OAuth user credentials (refresh token)**, not a service account | Service accounts have no storage quota on personal Drive |
| OAuth scope `drive.file` | Non-sensitive scope, no Google verification needed. Limitation: the app only sees files/folders **it created**, so the script creates the root folder itself |
| Google OAuth consent screen set to **"In production"** | In "Testing" mode the refresh token expires after 7 days and the sync silently dies |
| State in `state.json` committed to the repo | Free persistence between runs; commits also count as repo activity |
| Folder IDs stored in state (channel ID → folder ID) | No fragile name lookups; channel renames don't create duplicate folders |
| Folders created lazily (only when a channel has a first attachment) | No empty folders for chat-only channels |
| Idempotency via Drive `appProperties` (`discord_att` = attachment ID) | A crash between upload and state save can never cause duplicate uploads |
| Time budget (25 min) inside the script | Big backfills resume across runs instead of being killed mid-way |

**Repo visibility and free minutes:** a *private* repo gets ~2,000 free Actions minutes/month. At every 30 min, each run takes ~1 billed minute, so about 1,440 min/month, which fits. At every 15 min it would exceed the quota. A *public* repo has unlimited free minutes (so 15 min is fine), but then `state.json` is public (it only contains channel IDs, message IDs, and Drive folder IDs, no secrets). **Default: private repo, `*/30`.** The human should verify current GitHub quotas.

## 4. Human setup steps (the agent cannot do these)

### 4.1 Discord

1. Go to <https://discord.com/developers/applications> → **New Application** (name it e.g. `Course Drive Sync`).
2. **Bot** tab:
   - Click **Reset Token** → copy it (this is `DISCORD_BOT_TOKEN`). Keep it secret.
   - Under **Privileged Gateway Intents**, enable **MESSAGE CONTENT INTENT**. (Without it, Discord returns messages with attachments stripped out.)
   - Leave **Public Bot** enabled so the class rep can add it.
3. Build the invite link (replace `APP_ID` with the Application ID from the General Information tab):
   `https://discord.com/oauth2/authorize?client_id=APP_ID&scope=bot&permissions=66560`
   (66560 = View Channels + Read Message History. Nothing else.)
4. **Send that link to the class rep** (needs "Manage Server" permission). They open it, pick the server, click Authorize.
5. If module channels are restricted by role, the rep must make sure the bot's role can **view** them and **read message history**.
6. Get the server ID: Discord → User Settings → Advanced → enable **Developer Mode**, then right-click the server icon → **Copy Server ID** (this is `DISCORD_GUILD_ID`).

### 4.2 Google Cloud (OAuth)

1. <https://console.cloud.google.com/> → create a new project (e.g. `discord-drive-sync`).
2. **APIs & Services → Library** → enable **Google Drive API**.
3. **OAuth consent screen** (may be called "Google Auth Platform"): User type **External**, fill in app name and your email. Add the scope `https://www.googleapis.com/auth/drive.file`.
4. **Publish the app** so the status is **"In production"**. (Do NOT leave it in "Testing".) You might see an "unverified app" warning later; click Advanced → continue. That is expected for personal use.
5. **Credentials → Create Credentials → OAuth client ID → Desktop app**. Download the JSON and save it as `client_secret.json` in the project folder (never commit it).
6. Locally, run `python get_google_token.py` (after `pip install -r requirements.txt`). A browser opens; log in with the Google account whose Drive should store the files. The script prints `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REFRESH_TOKEN`.

### 4.3 GitHub

1. Create a **private** repo and push the project files.
2. Repo → Settings → Secrets and variables → Actions → add these **secrets**:
   - `DISCORD_BOT_TOKEN`
   - `DISCORD_GUILD_ID`
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REFRESH_TOKEN`
3. Optional **variables** (same page, "Variables" tab):
   - `DRIVE_ROOT_FOLDER_NAME` (default `Discord Courses`)
   - `CHANNEL_DENYLIST` (comma-separated channel names or IDs to skip, e.g. `general,memes`)
4. Settings → Actions → General → Workflow permissions: **Read and write permissions** (the workflow also declares `contents: write`).

### 4.4 After the first successful run

Open Google Drive → the `Discord Courses` folder → **Share** it with classmates (viewer access, by email or link). The files are owned by the human's Google account and count against their Drive storage.

## 5. Files to create

### 5.1 Repo layout

```
.
├── .github/workflows/sync.yml
├── .gitignore
├── get_google_token.py
├── requirements.txt
├── state.json
└── sync.py
```

### 5.2 `requirements.txt`

```
requests>=2.31
google-api-python-client>=2.100
google-auth>=2.23
google-auth-oauthlib>=1.1
```

### 5.3 `.gitignore`

```
client_secret.json
.env
__pycache__/
```

### 5.4 `state.json` (initial content)

```json
{
  "root_folder_id": null,
  "last_checked_date": null,
  "channels": {}
}
```

### 5.5 `get_google_token.py` (run once, locally)

```python
"""One-time helper: opens a browser, logs in to Google, prints the refresh token."""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

print("\n=== Add these as GitHub secrets ===")
print("GOOGLE_CLIENT_ID     =", creds.client_id)
print("GOOGLE_CLIENT_SECRET =", creds.client_secret)
print("GOOGLE_REFRESH_TOKEN =", creds.refresh_token)
```

### 5.6 `sync.py`

```python
"""Mirror Discord attachments to Google Drive, one folder per channel."""
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

DISCORD_API = "https://discord.com/api/v10"
STATE_FILE = Path("state.json")
FOLDER_MIME = "application/vnd.google-apps.folder"
TEXT_CHANNEL_TYPES = {0, 5}  # text + announcement channels
MAX_RUNTIME = 25 * 60        # seconds; resume on next run if exceeded

BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = os.environ["DISCORD_GUILD_ID"]
ROOT_FOLDER_NAME = os.environ.get("DRIVE_ROOT_FOLDER_NAME") or "Discord Courses"
DENY = {x.strip().lower() for x in (os.environ.get("CHANNEL_DENYLIST") or "").split(",") if x.strip()}
DRY_RUN = os.environ.get("DRY_RUN") == "1"

START = time.time()
session = requests.Session()
session.headers["Authorization"] = f"Bot {BOT_TOKEN}"
session.headers["User-Agent"] = "DiscordBot (course-drive-sync, 1.0)"


def log(msg):
    print(msg, flush=True)


# ---------- state ----------
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"root_folder_id": None, "last_checked_date": None, "channels": {}}


def save_state(state):
    if DRY_RUN:
        return
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


# ---------- discord ----------
def discord_get(path, params=None):
    for _ in range(8):
        r = session.get(f"{DISCORD_API}{path}", params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 1)) + 0.5)
            continue
        if r.status_code in (500, 502, 503, 504):
            time.sleep(3)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Discord request kept failing: {path}")


def new_messages(channel_id, after):
    """Yield messages newer than `after`, oldest first."""
    cursor = after or "0"
    while True:
        batch = discord_get(f"/channels/{channel_id}/messages", {"after": cursor, "limit": 100})
        if not batch:
            return
        batch.sort(key=lambda m: int(m["id"]))
        yield from batch
        cursor = batch[-1]["id"]
        if len(batch) < 100:
            return


# ---------- drive ----------
def drive_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    creds.refresh(Request())
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def create_folder(drive, name, parent=None):
    meta = {"name": name, "mimeType": FOLDER_MIME}
    if parent:
        meta["parents"] = [parent]
    return drive.files().create(body=meta, fields="id").execute()["id"]


def attachment_already_uploaded(drive, folder_id, att_id):
    q = ("'%s' in parents and appProperties has { key='discord_att' and value='%s' } "
         "and trashed = false" % (folder_id, att_id))
    res = drive.files().list(q=q, fields="files(id)", pageSize=1).execute()
    return bool(res.get("files"))


def name_exists(drive, folder_id, name):
    safe = name.replace("\\", "\\\\").replace("'", "\\'")
    q = "'%s' in parents and name = '%s' and trashed = false" % (folder_id, safe)
    res = drive.files().list(q=q, fields="files(id)", pageSize=1).execute()
    return bool(res.get("files"))


def upload(drive, folder_id, name, path, mime, att_id):
    size = os.path.getsize(path)
    media = MediaFileUpload(path, mimetype=mime or "application/octet-stream",
                            resumable=size > 5 * 1024 * 1024)
    body = {"name": name, "parents": [folder_id], "appProperties": {"discord_att": att_id}}
    drive.files().create(body=body, media_body=media, fields="id").execute()


# ---------- helpers ----------
def sanitize(name):
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "unnamed"


def download(url, dest):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                f.write(chunk)


def handle_attachment(drive, state, cs, cname, msg, att):
    log(f"  #{cname}: {att['filename']} ({att.get('size', 0) // 1024} KB)")
    if DRY_RUN:
        return
    if not cs["folder_id"]:
        cs["folder_id"] = create_folder(drive, sanitize(cname), state["root_folder_id"])
        save_state(state)
    if attachment_already_uploaded(drive, cs["folder_id"], att["id"]):
        return
    name = f"{msg['timestamp'][:10]}_{sanitize(att['filename'])}"
    if name_exists(drive, cs["folder_id"], name):
        stem, ext = os.path.splitext(name)
        name = f"{stem}_{att['id'][-6:]}{ext}"
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "file")
        download(att["url"], path)
        upload(drive, cs["folder_id"], name, path, att.get("content_type"), att["id"])


def process_channel(drive, state, ch):
    cid, cname = ch["id"], ch["name"]
    cs = state["channels"].setdefault(cid, {"name": cname, "folder_id": None, "last_message_id": None})
    cs["name"] = cname
    for msg in new_messages(cid, cs["last_message_id"]):
        if time.time() - START > MAX_RUNTIME:
            log("Time budget reached; will resume on the next run.")
            return False
        for att in msg.get("attachments", []):
            handle_attachment(drive, state, cs, cname, msg, att)
        cs["last_message_id"] = msg["id"]
        save_state(state)
    return True


# ---------- main ----------
def main():
    state = load_state()
    drive = None if DRY_RUN else drive_service()

    if drive and not state.get("root_folder_id"):
        state["root_folder_id"] = create_folder(drive, ROOT_FOLDER_NAME)
        save_state(state)

    channels = [c for c in discord_get(f"/guilds/{GUILD_ID}/channels")
                if c["type"] in TEXT_CHANNEL_TYPES]
    channels.sort(key=lambda c: c.get("position", 0))
    log(f"Found {len(channels)} text channels")

    errors = 0
    for ch in channels:
        if ch["name"].lower() in DENY or ch["id"] in DENY:
            continue
        try:
            if not process_channel(drive, state, ch):
                break  # out of time
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else None
            if code in (403, 404):
                log(f"  Skipping #{ch['name']}: bot has no access ({code})")
            else:
                errors += 1
                log(f"  ERROR in #{ch['name']}: {e}")
        except (HttpError, RuntimeError, OSError) as e:
            errors += 1
            log(f"  ERROR in #{ch['name']}: {e}")

    state["last_checked_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    save_state(state)
    log("Done." if not errors else f"Done with {errors} error(s).")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
```

### 5.7 `.github/workflows/sync.yml`

```yaml
name: Sync Discord to Drive

on:
  schedule:
    - cron: "*/30 * * * *"   # every 30 min (use */15 only on a public repo)
  workflow_dispatch:          # manual "Run workflow" button

permissions:
  contents: write

concurrency:
  group: discord-drive-sync
  cancel-in-progress: false

jobs:
  sync:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - run: pip install -r requirements.txt

      - name: Run sync
        env:
          DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}
          DISCORD_GUILD_ID: ${{ secrets.DISCORD_GUILD_ID }}
          GOOGLE_CLIENT_ID: ${{ secrets.GOOGLE_CLIENT_ID }}
          GOOGLE_CLIENT_SECRET: ${{ secrets.GOOGLE_CLIENT_SECRET }}
          GOOGLE_REFRESH_TOKEN: ${{ secrets.GOOGLE_REFRESH_TOKEN }}
          DRIVE_ROOT_FOLDER_NAME: ${{ vars.DRIVE_ROOT_FOLDER_NAME }}
          CHANNEL_DENYLIST: ${{ vars.CHANNEL_DENYLIST }}
        run: python sync.py

      - name: Commit state
        if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add state.json
          git diff --cached --quiet || (git commit -m "chore: update sync state" && git push)
```

## 6. Test plan (run in this order)

1. **Discord-only dry run** (no Google needed yet), once the bot is in the server:
   ```bash
   pip install -r requirements.txt
   DRY_RUN=1 DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... python sync.py
   ```
   Expected: it lists the text channels and prints every attachment it finds. If the channel list is empty or attachments are missing: check the bot was added, has View Channels / Read Message History on those channels, and that **Message Content Intent** is enabled.
2. **Google auth**: run `python get_google_token.py`, confirm it prints a refresh token.
3. **Real run**: add secrets, then GitHub → Actions → "Sync Discord to Drive" → **Run workflow**. Expected: a `Discord Courses` folder appears in Drive with one subfolder per channel that has attachments; `state.json` is committed.
4. **Idempotency**: run the workflow again. Expected: no new uploads, no duplicates.
5. **New file**: have someone post a file in a module channel. After the next run it appears in that channel's folder, named `YYYY-MM-DD_originalname.ext`.
6. If the first backfill is large and logs "Time budget reached", just let the next scheduled runs (or manual runs) continue; it resumes where it stopped.

## 7. Known limitations / maintenance notes

- Scheduled GitHub runs can be delayed by several minutes at busy times. Fine for course files.
- Only attachments are mirrored. Links to external Drive/Docs files in message text are not copied (see extensions).
- Threads, forum channels, and forwarded-message attachments are not handled in v1.
- With `drive.file` scope the app only sees what it created. If someone **deletes or trashes** the `Discord Courses` folder or a channel subfolder in Drive, the stored folder ID goes stale. Fix: clear `root_folder_id` / that channel's `folder_id` in `state.json` (and `last_message_id` to re-backfill).
- Discord's CDN attachment URLs are temporary, but the script fetches fresh URLs from the API on every run, so this doesn't matter.
- GitHub may disable scheduled workflows on **public** repos after 60 days without activity. The script updates `last_checked_date` daily, which produces a commit and keeps the repo active.
- If the bot token ever leaks: Discord Developer Portal → Bot → Reset Token → update the GitHub secret.
- Only mirror content the class is allowed to share; the Drive folder should be shared only with classmates.

## 8. Optional extensions (only if the human asks)

- Also collect links posted in messages (Drive/Docs/Notion URLs) into a `_links.md` file per channel.
- Rename the Drive folder automatically when a Discord channel is renamed (state already stores the folder ID).
- Include thread attachments (list active/archived threads via the API).
- Notify a Discord webhook or email when new files are uploaded.
