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

# Category allowlist: e.g. "COURS AI S5, COURS CYBER S5, COURS SOFTWARE S5" or "COURS"
CATEGORY_ALLOWLIST = [
    x.strip() for x in (os.environ.get("CATEGORY_ALLOWLIST") or "").split(",")
    if x.strip()
]

# File filtering: exclude images, gifs, videos, audio by default
EXCLUDE_MEDIA = os.environ.get("EXCLUDE_MEDIA", "1").strip().lower() in ("1", "true", "yes")
ALLOWED_EXTENSIONS = {
    x.strip().lower().lstrip(".")
    for x in (os.environ.get("ALLOWED_EXTENSIONS") or "").split(",")
    if x.strip()
}
EXCLUDED_EXTENSIONS = {
    x.strip().lower().lstrip(".")
    for x in (os.environ.get("EXCLUDED_EXTENSIONS") or "").split(",")
    if x.strip()
}

MEDIA_EXTENSIONS = {
    # Images & GIFs
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".tiff", ".tif", ".heic",
    # Videos & animations
    ".mp4", ".mov", ".webm", ".avi", ".mkv", ".flv", ".wmv", ".m4v",
    # Audio
    ".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac",
}

START = time.time()
session = requests.Session()
session.headers["Authorization"] = f"Bot {BOT_TOKEN}"
session.headers["User-Agent"] = "DiscordBot (course-drive-sync, 1.0)"


def log(msg):
    print(msg, flush=True)


# ---------- state ----------
def load_state():
    if STATE_FILE.exists():
        st = json.loads(STATE_FILE.read_text())
        st.setdefault("categories", {})
        st.setdefault("channels", {})
        st.setdefault("root_folder_id", None)
        st.setdefault("last_checked_date", None)
        return st
    return {"root_folder_id": None, "last_checked_date": None, "categories": {}, "channels": {}}


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
def clean_category_name(name):
    """Strip leading/trailing decorative characters (pipes, bullets, arrows) from category names."""
    cleaned = re.sub(r'^[|│—\-\*\s>]+|[|│—\-\*\s>]+$', '', name).strip()
    return cleaned or name.strip()


def category_matches(category_name, allowlist):
    if not allowlist:
        return True
    norm_cat = clean_category_name(category_name).lower()
    raw_cat_lower = category_name.lower().strip()
    for item in allowlist:
        norm_item = clean_category_name(item).lower()
        raw_item_lower = item.lower().strip()
        if not norm_item and not raw_item_lower:
            continue
        if norm_item == norm_cat or norm_item in norm_cat:
            return True
        if raw_item_lower in raw_cat_lower:
            return True
    return False


def is_allowed_file(att):
    filename = att.get("filename", "")
    content_type = (att.get("content_type") or "").lower()
    ext = os.path.splitext(filename)[1].lower()
    bare_ext = ext.lstrip(".")

    if EXCLUDED_EXTENSIONS and bare_ext in EXCLUDED_EXTENSIONS:
        return False

    if ALLOWED_EXTENSIONS:
        return bare_ext in ALLOWED_EXTENSIONS

    if EXCLUDE_MEDIA:
        if ext in MEDIA_EXTENSIONS:
            return False
        if any(content_type.startswith(prefix) for prefix in ("image/", "video/", "audio/")):
            return False

    return True


def sanitize(name):
    cleaned = re.sub(r'^[|│—\-\*\s>]+|[|│—\-\*\s>]+$', '', name).strip()
    return re.sub(r'[\\/:*?"<>|]+', "_", cleaned).strip() or "unnamed"


def download(url, dest):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                f.write(chunk)


def handle_attachment(drive, state, cs, cname, msg, att, target_folder_id):
    if not is_allowed_file(att):
        log(f"  #{cname}: Skipping non-document file '{att['filename']}'")
        return

    log(f"  #{cname}: {att['filename']} ({att.get('size', 0) // 1024} KB)")
    if DRY_RUN:
        return
    if not cs.get("folder_id"):
        cs["folder_id"] = create_folder(drive, sanitize(cname), target_folder_id)
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


def process_channel(drive, state, ch, category_name=None):
    cid, cname = ch["id"], ch["name"]
    cat_id = ch.get("parent_id")
    target_folder_id = state["root_folder_id"]

    if drive and cat_id and category_name:
        cat_clean = clean_category_name(category_name)
        cat_state = state["categories"].setdefault(cat_id, {"name": cat_clean, "folder_id": None})
        if not cat_state.get("folder_id"):
            log(f"Creating Drive category folder: '{cat_clean}'")
            cat_state["folder_id"] = create_folder(drive, sanitize(cat_clean), state["root_folder_id"])
            cat_state["name"] = cat_clean
            save_state(state)
        target_folder_id = cat_state["folder_id"]

    cs = state["channels"].setdefault(cid, {"name": cname, "folder_id": None, "last_message_id": None, "category_id": cat_id})
    cs["name"] = cname
    cs["category_id"] = cat_id

    for msg in new_messages(cid, cs["last_message_id"]):
        if time.time() - START > MAX_RUNTIME:
            log("Time budget reached; will resume on the next run.")
            return False
        for att in msg.get("attachments", []):
            handle_attachment(drive, state, cs, cname, msg, att, target_folder_id)
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

    categories = {c["id"]: c.get("name", "") for c in raw_channels if c.get("type") == 4}
    text_channels = [c for c in raw_channels if c.get("type") in TEXT_CHANNEL_TYPES]

    log(f"Server categories found ({len(categories)}): {list(categories.values())}")
    log(f"Total text channels visible ({len(text_channels)}):")
    for ch in text_channels:
        cat_disp = clean_category_name(categories.get(ch.get("parent_id"), "No Category"))
        log(f"  • #{ch['name']} (under: '{cat_disp}')")

    if CATEGORY_ALLOWLIST:
        log(f"Filtering channels by categories: {CATEGORY_ALLOWLIST}")
        channels = [
            c for c in text_channels
            if c.get("parent_id") and category_matches(categories.get(c.get("parent_id"), ""), CATEGORY_ALLOWLIST)
        ]
    else:
        channels = text_channels

    channels.sort(key=lambda c: (clean_category_name(categories.get(c.get("parent_id"), "")), c.get("position", 0)))
    log(f"Found {len(channels)} text channel(s) to sync:")
    for ch in channels:
        cat_disp = clean_category_name(categories.get(ch.get("parent_id"), "No Category"))
        log(f"  • [{cat_disp}] #{ch['name']}")

    errors = 0
    for ch in channels:
        if ch["name"].lower() in DENY or ch["id"] in DENY:
            continue
        cat_name = categories.get(ch.get("parent_id"))
        try:
            if not process_channel(drive, state, ch, cat_name):
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
