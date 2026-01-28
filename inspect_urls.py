import os
import json
import time
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
import google.auth

# Configuration
SITE_URL = "https://wordsolverx.com/"
PAGES_FILE = "pages.txt"

# Scopes
SCOPES = [
    'https://www.googleapis.com/auth/webmasters.readonly',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]

def get_credentials():
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not creds_json:
        # For local testing, look for credentials.json
        if os.path.exists('credentials.json'):
            return service_account.Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
        else:
            raise Exception("GOOGLE_CREDENTIALS environment variable not set and credentials.json not found.")
    
    creds_dict = json.loads(creds_json)
    return service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

def generate_dynamic_urls():
    urls = []
    games = ['wordle', 'quordle', 'colordle', 'semantle', 'phoodle']
    today = datetime.now()
    
    for i in range(7):
        date = today - timedelta(days=i)
        # Format: january-28-2026
        date_str = date.strftime("%B-%d-%Y").lower()
        for game in games:
            url = f"{SITE_URL}{game}-answer-for-{date_str}"
            urls.append(url)
    return urls

def read_static_urls():
    if not os.path.exists(PAGES_FILE):
        print(f"Warning: {PAGES_FILE} not found.")
        return []
    
    with open(PAGES_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip()]
    return urls

def create_google_sheet(sheets_service):
    today_str = datetime.now().strftime("%d%b-%Y").lower()
    sheet_title = f"wordsolverx-{today_str}"
    
    spreadsheet = {
        'properties': {
            'title': sheet_title
        }
    }
    
    # Create the spreadsheet directly
    try:
        file = sheets_service.spreadsheets().create(body=spreadsheet, fields='spreadsheetId').execute()
        spreadsheet_id = file.get('spreadsheetId')
        print(f"Created new spreadsheet: {sheet_title} (ID: {spreadsheet_id})")
        
        # Initialize the sheet with headers
        headers = [
            "Inspection Date", "URL", "Verdict", "Coverage State", 
            "Robots Txt State", "Indexing State", "Last Crawl Time", 
            "Page Fetch State", "Google Canonical", "User Canonical"
        ]
        
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="Sheet1!A1",
            valueInputOption="RAW",
            body={"values": [headers]}
        ).execute()
        
        return spreadsheet_id
    except Exception as e:
        if "403" in str(e):
            print("\n" + "!"*50)
            print("PERMISSION ERROR (403): The Service Account missing permissions.")
            print("ACTION REQUIRED:")
            print("1. Go to Google Cloud Console -> APIs & Services -> Library.")
            print("2. Search for 'Google Sheets API' and ensure it's ENABLED.")
            print("3. Search for 'Google Drive API' and ensure it's ALSO ENABLED (required for creating sheets).")
            print("4. Ensure your Service Account belongs to the SAME project where you enabled these APIs.")
            print("!"*50 + "\n")
        raise e

def inspect_url(search_service, url):
    try:
        request = {
            'inspectionUrl': url,
            'siteUrl': SITE_URL
        }
        response = search_service.urlInspection().index().inspect(body=request).execute()
        result = response.get('inspectionResult', {})
        
        index_result = result.get('indexStatusResult', {})
        
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            url,
            index_result.get('verdict', 'N/A'),
            index_result.get('coverageState', 'N/A'),
            index_result.get('robotsTxtState', 'N/A'),
            index_result.get('indexingState', 'N/A'),
            index_result.get('lastCrawlTime', 'N/A'),
            index_result.get('pageFetchState', 'N/A'),
            index_result.get('googleCanonical', 'N/A'),
            index_result.get('userCanonical', 'N/A')
        ]
        return row
    except Exception as e:
        print(f"Error inspecting {url}: {e}")
        return [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), url, "ERROR", str(e), "", "", "", "", "", ""]

def main():
    print("Starting URL Inspection script...")
    dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'
    
    try:
        creds = get_credentials()
        search_service = build('searchconsole', 'v1', credentials=creds)
        sheets_service = build('sheets', 'v4', credentials=creds)
        
        # 1. Generate URLs
        static_urls = read_static_urls()
        dynamic_urls = generate_dynamic_urls()
        all_urls = static_urls + dynamic_urls
        print(f"Total URLs to inspect: {len(all_urls)}")
        
        if not all_urls:
            print("No URLs found to inspect. Exiting.")
            return

        if dry_run:
            print("DRY RUN ENABLED. The following URLs would be inspected:")
            for url in all_urls:
                print(f" - {url}")
            print("Dry run complete. No API calls made to GSC or Drive/Sheets.")
            return

        # 2. Create Spreadsheet
        spreadsheet_id = create_google_sheet(sheets_service)
        
        # 3. Inspect and Append
        batch_size = 5 # Small batches to avoid timeout and show progress
        for i in range(0, len(all_urls), batch_size):
            batch = all_urls[i:i+batch_size]
            rows = []
            for url in batch:
                print(f"Inspecting: {url}")
                row = inspect_url(search_service, url)
                rows.append(row)
                # Respect API quotas (approx 2000 per property per day, but let's be safe)
                time.sleep(1) 
            
            sheets_service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range="Sheet1!A2",
                valueInputOption="RAW",
                body={"values": rows}
            ).execute()
            print(f"Appended {len(rows)} rows to Google Sheet.")
            
        print("Success! URL Inspection complete.")
        
    except Exception as e:
        print(f"Fatal Error: {e}")

if __name__ == "__main__":
    main()
