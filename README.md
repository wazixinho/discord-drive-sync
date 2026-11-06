# Discord to Google Drive Sync

[![Ask DeepWiki](https://devin.ai/assets/askdeepwiki.png)](https://deepwiki.com/wazixinho/discord-drive-sync)

Automatically sync file attachments from your Discord server channels to corresponding folders in your Google Drive. This project uses a serverless approach, running on a free, scheduled GitHub Actions workflow, eliminating the need for a 24/7 running server or PC.

## How It Works

This is not a traditional, always-online Discord bot. Instead, a Python script (`sync.py`) runs on a schedule (e.g., every 30 minutes) using GitHub Actions. In each run, the script:

1.  Authenticates with Discord (read-only) and Google Drive.
2.  Lists all text channels in your server.
3.  For each channel, it fetches messages that are newer than the last one it processed.
4.  Downloads any file attachments from those new messages.
5.  Uploads the attachments to a dedicated folder in Google Drive, named after the Discord channel (e.g., `Discord Courses/lecture-notes/`).
6.  Saves its progress (the ID of the last message processed per channel) to a `state.json` file.
7.  Commits the updated `state.json` back to the repository to ensure the next run picks up where it left off.

This process is idempotent, meaning it never uploads the same file twice, even if a run is interrupted.

## Features

-   **Serverless & Free**: Runs entirely on the GitHub Actions free tier. No server hosting required.
-   **Automatic History Backfill**: On the first run, it processes the entire message history of all channels to sync existing files.
-   **Stateful & Resilient**: Resumes from where it left off, preventing duplicate uploads and handling large backfills across multiple runs.
-   **Automatic Folder Creation**: Automatically creates a new folder in Google Drive when a file is posted in a new Discord channel.
-   **Read-Only on Discord**: The bot only requires permissions to view channels and read message history. It never writes messages or alters your server.
-   **Configurable**: Easily exclude specific channels from the sync using a denylist.

## Setup Instructions

Follow these steps to configure your credentials and activate the sync.

### Step 1: Discord Setup

#### 1.1 Create the Discord Bot & Get Token
1.  Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2.  Click **New Application** and give it a name (e.g., `Drive Sync Bot`).
3.  Navigate to the **Bot** tab on the left sidebar.
4.  Click **Reset Token** (or **Add Bot** / **View Token**), copy the token, and save it. This is your `DISCORD_BOT_TOKEN`.
5.  Scroll down to **Privileged Gateway Intents** and enable **MESSAGE CONTENT INTENT**. This is crucial for the bot to see file attachments.
6.  Click **Save Changes**.

#### 1.2 Get the Server ID
1.  In your Discord app, go to **User Settings > Advanced** and enable **Developer Mode**.
2.  Right-click on your server's icon in the server list and select **Copy Server ID**. This is your `DISCORD_GUILD_ID`.

#### 1.3 Invite the Bot to Your Server
1.  Go back to the Developer Portal, select your application, and go to the **General Information** tab.
2.  Copy the **Application ID**.
3.  Create an invite link by replacing `YOUR_APPLICATION_ID` in the URL below:
    ```
    https://discord.com/oauth2/authorize?client_id=YOUR_APPLICATION_ID&scope=bot&permissions=66560
    ```
    *(The permission code `66560` grants only 'View Channels' and 'Read Message History').*
4.  Open the link and add the bot to your desired server. Ensure the bot's role has permission to view the channels you want to sync.

---

### Step 2: Google Cloud Setup

#### 2.1 Create Cloud Project & Enable Drive API
1.  Open the [Google Cloud Console](https://console.cloud.google.com/).
2.  Create a **New Project** (e.g., `discord-drive-sync`).
3.  Go to **APIs & Services > Library**.
4.  Search for **Google Drive API** and click **Enable**.

#### 2.2 Configure OAuth Consent Screen
1.  Go to **APIs & Services > OAuth consent screen**.
2.  Select User Type: **External** and click **Create**.
3.  Provide an app name (e.g., `Discord Drive Sync`) and your email for support and developer contact.
4.  On the **Scopes** screen, click **Add or Remove Scopes**. Manually add the scope: `https://www.googleapis.com/auth/drive.file`.
5.  After saving, go back to the consent screen dashboard and click **Publish App**. Confirm to set the publishing status to **In production**. This prevents your refresh token from expiring every 7 days.

#### 2.3 Create OAuth Client Credentials
1.  Go to **APIs & Services > Credentials**.
2.  Click **+ Create Credentials > OAuth client ID**.
3.  Select Application type: **Desktop app**.
4.  Give it a name and click **Create**.
5.  Click **Download JSON** and rename the downloaded file to `client_secret.json`. Place this file in your local project directory.

---

### Step 3: Generate Your Google Refresh Token

You need to run a Python script locally to authorize the application and get a long-lived refresh token.

1.  Clone this repository to your local machine.
2.  Place the `client_secret.json` file from the previous step into the root of the cloned repository.
3.  Set up a Python environment and install dependencies:
    ```sh
    pip install -r requirements.txt
    ```
4.  Run the token generation script:
    ```sh
    python get_google_token.py
    ```
5.  A browser window will open. Log in with the Google account whose Drive you want to use for storage.
6.  Grant the requested permissions. You may see an "unverified app" warning; click **Advanced** and proceed.
7.  The script will print the Client ID, Client Secret, and Refresh Token in your terminal. Keep these values for the next step.

---

### Step 4: Add GitHub Secrets

The workflow requires your credentials to be stored as encrypted secrets in your GitHub repository.

1.  In your GitHub repository, go to **Settings > Secrets and variables > Actions**.
2.  Switch to the **Secrets** tab and click **New repository secret** for each of the following:
    -   `DISCORD_BOT_TOKEN`: The token from Step 1.1.
    -   `DISCORD_GUILD_ID`: The server ID from Step 1.2.
    -   `GOOGLE_CLIENT_ID`: The client ID from Step 3.
    -   `GOOGLE_CLIENT_SECRET`: The client secret from Step 3.
    -   `GOOGLE_REFRESH_TOKEN`: The refresh token from Step 3.

---

### Step 5: Run the Sync

The workflow is now fully configured.

1.  Go to the **Actions** tab of your repository.
2.  In the left sidebar, click on the **Sync Discord to Drive** workflow.
3.  Click the **Run workflow** dropdown on the right, and then the green **Run workflow** button to start the first sync.
4.  You can click on the running job to view the logs in real-time.
5.  After the workflow completes, check your Google Drive for a new folder (default name `Discord Courses`) containing your synced files. The `state.json` file in your repository will also be updated.

The sync will now run automatically every 30 minutes.

## Configuration (Optional)

You can customize the script's behavior using GitHub repository variables. Go to **Settings > Secrets and variables > Actions** and switch to the **Variables** tab.

-   `DRIVE_ROOT_FOLDER_NAME`: The name of the main folder created in Google Drive. Defaults to `Discord Courses`.
-   `CHANNEL_DENYLIST`: A comma-separated list of channel names or IDs to exclude from the sync (e.g., `general,memes,123456789012345678`).

## Troubleshooting

-   **Bot has no access to a channel**: If the logs show `Skipping #[channel-name]: bot has no access (403)`, ensure the bot's role in Discord has "View Channel" and "Read Message History" permissions for that specific channel.
-   **Missing Attachments**: Ensure the **Message Content Intent** is enabled for your bot in the Discord Developer Portal (Step 1.1).
-   **Sync stops working after 7 days**: This happens if your Google OAuth Consent Screen is in "Testing" mode instead of "In production". Follow Step 2.2 to publish the app. You will need to re-run `get_google_token.py` to generate a new refresh token.
-   **Drive folder was deleted**: If the root folder or a channel subfolder is deleted in Google Drive, the script will fail. To fix this, manually edit `state.json` in your repository, set the `root_folder_id` or the specific channel's `folder_id` to `null`, and the script will recreate it on the next run.
