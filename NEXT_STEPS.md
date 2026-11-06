# Next Steps: Discord to Google Drive Auto-Sync Setup

All core code, workflows, local environment, and your private GitHub repository have been automatically prepared and configured:
- **GitHub Repository**: [https://github.com/wazixinho/discord-drive-sync](https://github.com/wazixinho/discord-drive-sync) (Private)
- **Workflow Permissions**: Read and Write permissions are already enabled.
- **Python Environment**: `.venv` is created and dependencies are installed.

Follow these remaining steps to provide your credentials and activate the sync.

---

## Step 1: Discord Setup

### 1.1 Create the Discord Bot & Copy Token
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** (top right) and give it a name (e.g. `Course Drive Sync`).
3. In the left sidebar, click **Bot**:
   - Click **Reset Token** (or **Add Bot** / **View Token**), copy the token, and save it somewhere secure. This is your `DISCORD_BOT_TOKEN`.
   - Scroll down to **Privileged Gateway Intents**.
   - Enable **MESSAGE CONTENT INTENT** *(crucial: without this, Discord strips all file attachments)*.
   - Ensure **Public Bot** is checked so the class representative can invite it.
   - Click **Save Changes**.

### 1.2 Get the Server ID (`DISCORD_GUILD_ID`)
1. In the Discord desktop or web app, go to **User Settings** (gear icon) → **Advanced** → enable **Developer Mode**.
2. Right-click the server's icon in the server list on the left → click **Copy Server ID**. This is your `DISCORD_GUILD_ID`.

### 1.3 Invite the Bot to the Server
1. Go back to the Discord Developer Portal → your application → **General Information**.
2. Copy the **Application ID**.
3. Create your invite link by replacing `YOUR_APPLICATION_ID` below:
   ```text
   https://discord.com/oauth2/authorize?client_id=YOUR_APPLICATION_ID&scope=bot&permissions=66560
   ```
   *(Permission `66560` grants only View Channels and Read Message History).*
4. Send this link to the server administrator or class rep (who has "Manage Server" permissions).
5. Ensure the bot's role has permission to view the module channels where class files are posted.

---

## Step 2: Google Cloud Setup (OAuth)

### 2.1 Create Cloud Project & Enable Drive API
1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project dropdown at the top → **New Project** → Name it `discord-drive-sync` → Click **Create**.
3. Go to **APIs & Services** → **Library**.
4. Search for **Google Drive API** → Click **Enable**.

### 2.2 Configure OAuth Consent Screen
1. In the left menu, go to **APIs & Services** → **OAuth consent screen** (or Google Auth Platform).
2. Select User Type: **External** → Click **Create**.
3. Enter App information:
   - **App name**: `Discord Drive Sync`
   - **User support email**: Your email address
   - **Developer contact information**: Your email address
   - Click **Save and Continue**.
4. **Scopes** screen:
   - Click **Add or Remove Scopes**.
   - Manually enter or search for: `https://www.googleapis.com/auth/drive.file`
   - Select it and click **Update**, then **Save and Continue**.
5. Back on the OAuth Consent Screen dashboard, locate **Publishing status**:
   - Click **Publish App** and confirm to set status to **"In production"**.
   - *(Important: Do NOT leave it in "Testing", otherwise Google refresh tokens expire after 7 days!)*

### 2.3 Create OAuth Client Credentials & Download JSON
1. Go to **APIs & Services** → **Credentials**.
2. Click **+ Create Credentials** (top) → **OAuth client ID**.
3. For **Application type**, choose **Desktop app**.
4. Name it `Desktop Sync Client` → Click **Create**.
5. In the dialog that appears, click **Download JSON**.
6. Rename the downloaded file to exactly:
   ```text
   client_secret.json
   ```
7. Move this `client_secret.json` file into this project folder:
   ```text
   C:\Users\Aymen\Desktop\discord Bot to sync with Gdrive-AGY\client_secret.json
   ```
   *(Note: `.gitignore` is already set up to protect `client_secret.json` from being committed).*

---

## Step 3: Generate Your Google Refresh Token

In your project directory, open PowerShell and run:

```powershell
.\.venv\Scripts\python get_google_token.py
```

A browser window will open automatically:
1. Log in with the Google account whose Google Drive will hold the course files.
2. If you see a warning screen saying *"Google hasn’t verified this app"*, click **Advanced** → **Go to Discord Drive Sync (unsafe)**.
3. Click **Continue** to grant permissions.
4. Return to your terminal. The script will print:
   ```text
   === Add these as GitHub secrets ===
   GOOGLE_CLIENT_ID     = ...
   GOOGLE_CLIENT_SECRET = ...
   GOOGLE_REFRESH_TOKEN = ...
   ```
Keep these three values ready.

---

## Step 4: Add GitHub Secrets

Because you have the GitHub CLI (`gh`) authenticated, you can set all 5 secrets with one command each in PowerShell:

```powershell
gh secret set DISCORD_BOT_TOKEN
gh secret set DISCORD_GUILD_ID
gh secret set GOOGLE_CLIENT_ID
gh secret set GOOGLE_CLIENT_SECRET
gh secret set GOOGLE_REFRESH_TOKEN
```
*(Each command will prompt you to paste the respective secret).*

**Alternative (via Web UI):**
Go to: [https://github.com/wazixinho/discord-drive-sync/settings/secrets/actions](https://github.com/wazixinho/discord-drive-sync/settings/secrets/actions)
Click **New repository secret** and add each of the 5 secrets above.

### 4.2 (Optional) Configure Channels, Categories & File Filters

You can configure what gets synchronized anytime using repository variables:

- **Filter by Categories** (sync only channels belonging to specific categories):
  ```powershell
  gh variable set CATEGORY_ALLOWLIST --body "COURS AI S5, COURS CYBER S5, COURS SOFTWARE S5"
  ```
  *(Or simply `--body "COURS"` to match any category starting with "COURS").*

- **Only Specific File Types** (e.g. only PDFs and SQL):
  ```powershell
  gh variable set ALLOWED_EXTENSIONS --body "pdf,sql"
  ```
  *(By default, all course documents, code, archives, and files are included, while all images, gifs, videos, and audio are automatically filtered out).*

- **Skip Specific Channels**:
  ```powershell
  gh variable set CHANNEL_DENYLIST --body "general,memes"
  ```

---

## Step 5: Test and Verify

### 5.1 (Optional) Local Dry Run (Discord check only)
You can test reading the Discord server without touching Google Drive:
```powershell
$env:DRY_RUN="1"
$env:DISCORD_BOT_TOKEN="your_bot_token_here"
$env:DISCORD_GUILD_ID="your_guild_id_here"
.\.venv\Scripts\python sync.py
```
It will list all text channels and attachments found without downloading or uploading anything.

### 5.2 Trigger the First Sync on GitHub Actions
1. Go to your repository Actions tab:
   [https://github.com/wazixinho/discord-drive-sync/actions](https://github.com/wazixinho/discord-drive-sync/actions)
2. In the left sidebar, click **Sync Discord to Drive**.
3. Click the **Run workflow** dropdown on the right → Click the green **Run workflow** button.
4. Click on the running workflow to watch real-time logs.
5. Once completed:
   - Open your Google Drive: you will see a new folder named `Discord Courses`.
   - Inside will be subfolders matching your Discord channel names with all uploaded attachments.
   - In GitHub, `state.json` will be automatically updated with the latest message IDs.

### 5.3 Share the Drive Folder with Classmates
1. In Google Drive, right-click the `Discord Courses` folder → **Share**.
2. Set general access to **Anyone with the link can view** (Viewer) or invite classmates by email.
3. The workflow will now automatically run every 30 minutes in the background for free.
