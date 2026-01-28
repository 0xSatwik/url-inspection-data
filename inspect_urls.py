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
    'https://www.googleapis.com/auth/drive'
]

def get_credentials():
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not creds_json:
        # For local testing, look for credentials.json
        if os.path.exists('credentials.json'):
            creds = service_account.Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
            print(f"Using credentials from file: {creds.service_account_email}")
            return creds
        else:
            raise Exception("GOOGLE_CREDENTIALS environment variable not set and credentials.json not found.")
    
    creds_dict = json.loads(creds_json)
    print(f"Using Service Account: {creds_dict.get('client_email')}")
    print(f"Project ID: {creds_dict.get('project_id')}")
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
        print(f"Created new spreadsheet: {sheet_title}")
        print(f"URL: https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")
        
        # Initialize the sheet with headers (same as before)
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
            print("PERMISSION ERROR (403) STILL PERSISTS.")
            print("If you have enabled APIs, it might be that the Service Account has NO access to create files.")
            print("TRY THIS:")
            print("1. Go to Google Cloud Console -> IAM & Admin -> IAM.")
            print("2. Find your Service Account in the list.")
            print("3. Click 'Edit Manager' (Pencil icon).")
            print("4. Add the role 'Editor' (or at least 'Project Viewer') to the Service Account.")
            print("!"*50 + "\n")
        raise e

def inspect_url(search_service, url, site_url):
    try:
        request = {
            'inspectionUrl': url,
            'siteUrl': site_url
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

def find_verified_property(service):
    """
    Finds the correct siteUrl from the authenticated user's GSC account.
    Handles sc-domain: vs https:// prefixes.
    """
    try:
        site_list = service.sites().list().execute()
        sites = site_list.get('siteEntry', [])
        
        print("\nChecking verified GSC properties...")
        
        # 1. Look for exact match first
        for site in sites:
            site_url = site['siteUrl']
            permission = site['permissionLevel']
            print(f" - Found property: {site_url} (Access: {permission})")
            
            if "wordsolverx.com" in site_url and permission != "siteRestrictedUser":
                return site_url

        print("ERROR: Could not find a GSC property for 'wordsolverx.com' in this Service Account.")
        print("Please ensure you have added the Service Account email as an 'Owner' or 'Full User' to the property in Google Search Console.")
        return None
        
    except Exception as e:
        print(f"Error listing sites: {e}")
        return None

def main():
    print("Starting URL Inspection script...")
    dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'
    
    try:
        creds = get_credentials()
        search_service = build('searchconsole', 'v1', credentials=creds)
        sheets_service = build('sheets', 'v4', credentials=creds)
        
        # 0. Find Correct Site URL
        print("Verifying GSC Access...")
        site_url = find_verified_property(search_service)
        if not site_url:
            print("Aborting: No access to wordsolverx.com property found.")
            return
        print(f"Using GSC Property: {site_url}\n")
        
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
            print("Dry run complete. No API calls made to GSC or Sheets.")
            return

        # 2. Try to Create Spreadsheet
        spreadsheet_id = None
        csv_mode = False
        try:
            spreadsheet_id = create_google_sheet(sheets_service)
        except Exception as e:
            print(f"\n[WARNING] Google Sheets creation failed: {e}")
            print("Falling back to CSV creation...\n")
            csv_mode = True
        
        # 3. Inspect URLs
        all_rows = []
        headers = [
            "Inspection Date", "URL", "Verdict", "Coverage State", 
            "Robots Txt State", "Indexing State", "Last Crawl Time", 
            "Page Fetch State", "Google Canonical", "User Canonical"
        ]
        
        batch_size = 5
        for i in range(0, len(all_urls), batch_size):
            batch = all_urls[i:i+batch_size]
            batch_rows = []
            for url in batch:
                print(f"Inspecting: {url}")
                row = inspect_url(search_service, url, site_url)
                batch_rows.append(row)
                all_rows.append(row)
                time.sleep(1) 
            
            if not csv_mode and spreadsheet_id:
                try:
                    sheets_service.spreadsheets().values().append(
                        spreadsheetId=spreadsheet_id,
                        range="Sheet1!A2",
                        valueInputOption="RAW",
                        body={"values": batch_rows}
                    ).execute()
                    print(f"Appended {len(batch_rows)} rows to Google Sheet.")
                except Exception as e:
                    print(f"Failed to append to Google Sheet: {e}. Switching to CSV fallback for remaining rows.")
                    csv_mode = True
            
        # 4. Final CSV Export if in CSV mode
        if csv_mode:
            import csv
            today_str = datetime.now().strftime("%d%b-%Y").lower()
            csv_filename = f"wordsolverx-{today_str}.csv"
            with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(all_rows)
            print(f"\nSuccess! Results saved to local file: {csv_filename}")
        else:
            print("\nSuccess! Results saved to Google Sheets.")
            
    except Exception as e:
        print(f"Fatal Error: {e}")

if __name__ == "__main__":
    main()
