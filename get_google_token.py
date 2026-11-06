"""One-time helper: opens a browser, logs in to Google, prints the refresh token."""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

print("\n=== Add these as GitHub secrets ===")
print("GOOGLE_CLIENT_ID     =", creds.client_id)
print("GOOGLE_CLIENT_SECRET =", creds.client_secret)
print("GOOGLE_REFRESH_TOKEN =", creds.refresh_token)
