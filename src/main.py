import csv
import os
import re
import sys
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import time

def extract_meet_name(url):
    """Extract the meet name from the URL."""
    match = re.search(r'/(\d+)(?:-([^/]+))?/results', url)
    if match:
        if match.group(2):  # If meet name is in the URL
            return match.group(2).replace('-', ' ')
        else:
            return f"Meet {match.group(1)}"
    return "Unknown Meet"

def standardize_url(url):
    """Standardize the URL format to use just the meet ID."""
    match = re.search(r'/meets/(\d+)(?:-[^/]+)?/results', url)
    if match:
        return f"https://co.milesplit.com/meets/{match.group(1)}/results"
    return url

def login_and_get_content_with_playwright(url, username, password):
    """Login to the website and get the page content using Playwright."""
    with sync_playwright() as p:
        print("Using Playwright for login (required for reCAPTCHA handling)...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        
        try:
            # First navigate to the main site to establish cookies
            print("Navigating to main site first...")
            page.goto('https://co.milesplit.com/', wait_until="domcontentloaded", timeout=30000)
            
            # Navigate to the login page
            print("Navigating to login page...")
            page.goto('https://co.milesplit.com/login', wait_until="domcontentloaded", timeout=30000)
            
            # Fill in the login form
            print("Filling in login form...")
            page.fill('input[name="email"]', username)
            page.fill('input[name="password"]', password)
            
            # Wait a bit for reCAPTCHA to initialize
            page.wait_for_timeout(2000)
            
            # Create debug directory if it doesn't exist
            os.makedirs('debug', exist_ok=True)
            
            # Click the login button
            print("Submitting login form...")
            page.click('button[type="submit"]')
            
            # Wait for the login process to start
            print("Waiting for login process to start...")
            page.wait_for_timeout(2000)
            page.screenshot(path="debug/login_started.png")
            
            # Now we need to wait for the login process to complete
            # This could involve a modal disappearing or being redirected
            
            print("Waiting for login process to complete...")
            
            # Try different approaches to detect when login is complete
            
            # Approach 1: Wait for any login modal/overlay to disappear
            max_wait_time = 30  # seconds
            start_time = time.time()
            login_complete = False
            
            while time.time() - start_time < max_wait_time:
                # Take a screenshot every few seconds to track progress
                page.screenshot(path=f"debug/login_wait_{int(time.time() - start_time)}.png")
                
                # Check if we're still on the login page
                if not "login" in page.url.lower():
                    print(f"Redirected to: {page.url}")
                    login_complete = True
                    break
                
                # Check if any login modal is visible
                modal_visible = page.evaluate('''() => {
                    const modals = document.querySelectorAll('.modal, .overlay, .loading');
                    for (const modal of modals) {
                        if (window.getComputedStyle(modal).display !== 'none') {
                            return true;
                        }
                    }
                    return false;
                }''')
                
                if not modal_visible:
                    print("Login modal no longer visible")
                    login_complete = True
                    break
                
                print(f"Still waiting for login to complete... ({int(time.time() - start_time)}s)")
                page.wait_for_timeout(2000)  # Check every 2 seconds
            
            if not login_complete:
                print("Login process timed out after waiting")
                page.screenshot(path="debug/login_timeout.png")
                return None
            
            # Now take a screenshot after login
            page.screenshot(path="debug/after_login.png")
            print(f"After login screenshot saved to debug/after_login.png")
            
            # Check if we're actually logged in by looking for user-specific elements
            is_logged_in = page.evaluate('''() => {
                // Look for elements that would indicate a logged-in state
                const userMenus = document.querySelectorAll('.user-menu, .avatar, .profile-link');
                return userMenus.length > 0;
            }''')
            
            print(f"Logged in status detected: {is_logged_in}")
            
            if not is_logged_in:
                # Try another approach - check if we can see any logout links
                logout_link = page.query_selector('a:text("Logout"), a:text("Sign Out")')
                if logout_link:
                    print("Found logout link - user is logged in")
                    is_logged_in = True
            
            if not is_logged_in:
                print("Failed to confirm logged in status")
                return None
                
            # Now navigate to the results page
            print("Login successful!")
            
            # Standardize the URL format
            std_url = standardize_url(url)
            print(f"Standardized URL: {std_url}")
            
            # Navigate to the results page with explicit flags
            print(f"Navigating to results page: {std_url}")
            
            # Let's try a more direct approach - ensure we're fully loaded before navigating
            page.wait_for_timeout(3000)  # Give a moment for any post-login processes
            
            try:
                response = page.goto(std_url, wait_until="domcontentloaded", timeout=60000)
                if response:
                    print(f"Navigation response status: {response.status}")
                    if response.status >= 400:
                        print(f"Error response received: {response.status}")
                        page.screenshot(path="debug/error_response.png")
                else:
                    print("No response object received")
            except Exception as e:
                print(f"Navigation error: {str(e)}")
                page.screenshot(path="debug/navigation_error.png")
            
            # Wait for the page to stabilize
            print("Waiting for page to stabilize...")
            page.wait_for_timeout(8000)  # Wait longer to ensure scripts load
            
            # Take a screenshot of the results page
            page.screenshot(path="debug/results_page.png")
            print(f"Results page screenshot saved to debug/results_page.png")
            
            # Check the current URL to confirm we're on the results page
            results_url = page.url
            print(f"Current URL of results page: {results_url}")
            
            # Debug: Check if we have any tables or key content
            tables_count = page.evaluate('''() => document.querySelectorAll('table').length''')
            print(f"Number of tables on page: {tables_count}")
            
            # Get the page content
            content = page.content()
            
            # Save raw content for debugging
            with open("debug/raw_page_content.html", "w", encoding="utf-8") as f:
                f.write(content)
            
            return content
        
        except Exception as e:
            print(f"Error during Playwright scraping: {str(e)}")
            try:
                page.screenshot(path="debug/error_state.png")
                print(f"Error state screenshot saved to debug/error_state.png")
                return page.content()
            except Exception as inner_e:
                print(f"Failed to get content after error: {str(inner_e)}")
                return None
        finally:
            browser.close()

def parse_results(html_content, meet_name, target_school):
    """Parse the results HTML and extract data for target_school athletes."""
    if not html_content:
        print("No HTML content to parse")
        return []
        
    soup = BeautifulSoup(html_content, 'html.parser')
    results_list = []
    
    # Save the HTML for debugging regardless
    os.makedirs('debug', exist_ok=True)
    with open("debug/page_content.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("Page content saved to debug/page_content.html for inspection")
    
    # First, just check if our target school is mentioned anywhere
    school_mentions = soup.find_all(string=re.compile(target_school))
    print(f"Mentions of {target_school} on the page: {len(school_mentions)}")
    
    # Look for any result tables
    all_tables = soup.find_all('table')
    print(f"Found {len(all_tables)} tables on the page")
    
    # Direct approach: Find tables with event results
    event_tables = []
    event_names = []
    
    # Find all potential event containers and event names
    event_headers = soup.select('div.eventHeader, h3.eventHeader, .event-header')
    print(f"Found {len(event_headers)} event headers")
    
    # If we can't find event headers, try to find the tables directly
    if not event_headers:
        # Find tables that look like result tables (have athlete and team columns)
        for table in all_tables:
            # Check if this table has headers or rows that indicate it's a results table
            has_athlete_col = table.select_one('th.athlete, td.athlete')
            has_team_col = table.select_one('th.team, td.team')
            
            if has_athlete_col and has_team_col:
                # This looks like a results table
                # Try to find an associated event name
                event_name = None
                
                # Look for an event name in previous siblings
                prev_elem = table.find_previous(['h2', 'h3', 'h4', 'p', 'div.eventName'])
                if prev_elem:
                    event_name = prev_elem.text.strip()
                
                if not event_name:
                    event_name = "Unknown Event"
                    
                event_tables.append(table)
                event_names.append(event_name)
    else:
        # Process each event header to find associated tables
        for header in event_headers:
            event_name = header.text.strip()
            print(f"Found event header: {event_name}")
            
            # Find the table that follows this header
            event_table = header.find_next('table')
            if event_table:
                event_tables.append(event_table)
                event_names.append(event_name)
    
    # If we still haven't found event tables, look for any tables with our target school
    if not event_tables:
        print(f"Trying direct table search for {target_school}...")
        for table in all_tables:
            school_in_table = table.find(string=re.compile(target_school))
            if school_in_table:
                # Try to find an event name for this table
                prev_elem = table.find_previous(['h2', 'h3', 'h4', 'p', 'div.eventName'])
                event_name = prev_elem.text.strip() if prev_elem else "Unknown Event"
                
                event_tables.append(table)
                event_names.append(event_name)
    
    print(f"Found {len(event_tables)} event tables to process")
    
    # Process each event table
    for i, table in enumerate(event_tables):
        event_name = event_names[i] if i < len(event_names) else "Unknown Event"
        print(f"Processing event: {event_name}")
        
        # Determine gender based on event name
        gender = "Boys" if "Boys" in event_name else "Girls" if ("Girls" in event_name or "Womens" in event_name) else "Unknown"
        
        # Extract the actual event from the full name
        event = event_name.replace("Boys ", "").replace("Girls ", "").replace("Womens ", "").strip()
        
        # Find all rows in the table that contain results
        rows = table.select('tbody tr')
        print(f"  - Found {len(rows)} result rows")
        
        for row in rows:
            # Check if the athlete is from our target school
            team_element = row.select_one('td.team a')
            
            # Only process rows where the team is our target school
            if not team_element or target_school not in team_element.text:
                continue
                
            # Extract place
            place_element = row.select_one('td.place')
            place = place_element.text.strip() if place_element else ""
            
            # Extract athlete name
            athlete_element = row.select_one('td.athlete a')
            athlete_name = athlete_element.text.strip() if athlete_element else ""
            
            # Extract mark/finish time
            mark_element = row.select_one('td.finish')
            mark = mark_element.text.strip() if mark_element else ""
            
            # Only add the result if we have an athlete name and mark
            if athlete_name and mark:
                print(f"  - Found result: {athlete_name} - {place} - {mark}")
                
                # Add to results
                results_list.append({
                    'meet_name': meet_name,
                    'event': event,
                    'gender': gender,
                    'athlete_name': athlete_name,
                    'place': place,
                    'mark': mark
                })
    
    print(f"Found {len(results_list)} results for {target_school}")
    return results_list

def write_to_csv(results, output_file, target_school):
    """Write the results to a CSV file."""
    if not results:
        print(f"No results found for {target_school}")
        return
    
    fieldnames = ['meet_name', 'event', 'gender', 'athlete_name', 'place', 'mark']
    
    # Create a 'results' directory if it doesn't exist
    os.makedirs('results', exist_ok=True)
    output_path = os.path.join('results', output_file)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(result)
    
    print(f"Results written to {output_path}")

def main():
    """Main function to parse command-line arguments and run the script."""
    if len(sys.argv) != 2:
        print("Usage: python main.py <url>")
        sys.exit(1)
    
    url = sys.argv[1]
    
    # Load .env file
    load_dotenv()

    # Access variables
    username = os.getenv("USERNAME")
    password = os.getenv("PASSWORD")
    target_school = os.getenv("TARGET_SCHOOL", "Peak to Peak Charter School")  # Default if not set
    
    if not username or not password:
        print("Error: USERNAME and PASSWORD must be set in .env file")
        sys.exit(1)
        
    print(f"Target school: {target_school}")

    meet_name = extract_meet_name(url)
    print(f"Processing meet: {meet_name}")
    
    # Create output filename based on meet name
    output_file = f"{meet_name.replace(' ', '_')}_results.csv"
    
    # Create 'results' directory if it doesn't exist
    os.makedirs('results', exist_ok=True)
    output_path = os.path.join('results', output_file)
    
    # Check if the file already exists
    if os.path.exists(output_path):
        print(f"Results file {output_path} already exists. Skipping processing.")
        sys.exit(0)
    
    # Get content with Playwright which can handle reCAPTCHA
    html_content = login_and_get_content_with_playwright(url, username, password)
    
    if not html_content:
        print("Failed to retrieve content after authentication")
        sys.exit(1)
    
    # Parse results and write to CSV
    results = parse_results(html_content, meet_name, target_school)
    
    # Write results to CSV
    write_to_csv(results, output_file, target_school)

if __name__ == "__main__":
    main()