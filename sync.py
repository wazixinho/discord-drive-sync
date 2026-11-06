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
        if not r.ok:
            log(f"Discord API Error [{r.status_code}] on {path}: {r.text}")
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

    # Verify Discord bot token & identity
    try:
        me = discord_get("/users/@me")
        log(f"Discord Bot Authenticated: {me.get('username')} (ID: {me.get('id')})")
    except Exception as e:
        log(f"Failed to authenticate Discord bot: {e}")
        sys.exit(1)

    try:
        raw_channels = discord_get(f"/guilds/{GUILD_ID}/channels")
    except requests.HTTPError as e:
        log(f"\n[ERROR] Unable to access Discord Server (Guild ID: '{GUILD_ID}').")
        log("Common causes:")
        log("  1. The bot has NOT been invited into this server yet.")
        log("     Make sure you or the admin invited the bot using the OAuth2 invite link (Step 1.3 in NEXT_STEPS.md).")
        log("  2. DISCORD_GUILD_ID is incorrect.")
        log("     Verify by right-clicking the server's icon in Discord -> 'Copy Server ID'.")
        log("  3. The bot lacks permissions to view channels in the server.")
        sys.exit(1)

    channels = [c for c in raw_channels if c["type"] in TEXT_CHANNEL_TYPES]
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
