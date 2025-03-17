import csv
import os
import re
import sys
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import argparse
import logging
from playwright.sync_api import sync_playwright
import time
from datetime import date

#TODOS:
# - add a dict look up to get from "LJ" to "Long Jump" and so on for all events for --stateranks code path
# - remove "Finals" from event names when getting the data (before it get's to CSV)
# - add a "--debug" flag to save screenshots and HTML for debugging purposes, and not have this be default behavior
# - test running with a sleep=.1 and not .25

# Define the event types structure
EVENT_TYPES = {
    "all": [
        "100m",
        "200m",
        "400m",
        "300H",
        "800m",
        "1600m",
        "3200m",
        "D",
        "S",
        "HJ",
        "TJ",
        "LJ",
        "PV",
        "4x100m",
        "4x200m",
        "4x400m",
        "4x800m"
    ],
    "boysonly": ["110H"],
    "girlsonly": ["100H"]
}

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
    match = re.search(r'/meets/(\d+)(?:-[^/]+)?/results', url)
    if match:
        return f"https://co.milesplit.com/meets/{match.group(1)}/results"
    return url

def login_with_playwright(playwright, username, password):
    """Login to the website using Playwright and return the browser context."""
    print("Using Playwright for login (required for reCAPTCHA handling)...")
    browser = playwright.chromium.launch(headless=True)
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
        print("Waiting for login process to complete...")
        
        # Try different approaches to detect when login is complete
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
            
        # Login successful!
        print("Login successful!")
        return browser, context

    except Exception as e:
        print(f"Error during Playwright login: {str(e)}")
        try:
            page.screenshot(path="debug/error_state.png")
            print(f"Error state screenshot saved to debug/error_state.png")
        except Exception as inner_e:
            print(f"Failed to take screenshot after error: {str(inner_e)}")
        return None

def navigate_to_page_and_get_content(context, url):
    """Navigate to a URL using an existing browser context and get the page content."""
    page = context.new_page()
    
    try:
        print(f"Navigating to page: {url}")
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        if response:
            print(f"Navigation response status: {response.status}")
            if response.status >= 400:
                print(f"Error response received: {response.status}")
                page.screenshot(path="debug/error_response.png")
                return None
        else:
            print("No response object received")
        
        # Wait for the page to stabilize
        print("Waiting for page to stabilize...")
        page.wait_for_timeout(5000)
        
        # Take a screenshot of the page
        screenshot_path = f"debug/page_{int(time.time())}.png"
        page.screenshot(path=screenshot_path)
        print(f"Page screenshot saved to {screenshot_path}")
        
        # Get the page content
        content = page.content()
        
        # Save raw content for debugging
        debug_path = f"debug/raw_page_content_{int(time.time())}.html"
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        return content
    
    except Exception as e:
        print(f"Error during page navigation: {str(e)}")
        try:
            page.screenshot(path="debug/error_state.png")
            print(f"Error state screenshot saved to debug/error_state.png")
        except Exception as inner_e:
            print(f"Failed to take screenshot after error: {str(inner_e)}")
        return None
    finally:
        page.close()

def login_and_get_content_with_playwright(url, username, password):
    """Login to the website and get the page content using Playwright."""
    with sync_playwright() as playwright:
        result = login_with_playwright(playwright, username, password)
        
        if not result:
            return None
            
        browser, context = result
        
        try:
            # Standardize the URL format
            std_url = standardize_url(url)
            print(f"Standardized URL: {std_url}")
            
            content = navigate_to_page_and_get_content(context, std_url)
            return content
        
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
    
    fieldnames = ['meet_name', 'event', 'place', 'athlete_name', 'gender', 'mark']
    
    # Create a 'results' directory if it doesn't exist
    os.makedirs('results', exist_ok=True)
    output_path = os.path.join('results', output_file)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(result)
    
    print(f"Results written to {output_path}")

def get_state_ranks(target_school, username, password, year, league):
    """Get state rankings for the target school."""
    print(f"Getting state rankings for {target_school}...")
    
    # Using with statement to ensure playwright is properly closed
    with sync_playwright() as playwright:
        # Login with Playwright
        login_result = login_with_playwright(playwright, username, password)
        if not login_result:
            print("Failed to login for state rankings")
            return []
            
        browser, context = login_result
        
        try:
            all_results = []
            today = date.today().strftime("%Y-%m-%d")  # Format date as YYYY-MM-DD
            
            # Create the output file path
            output_file = f"StateRankings_{today}.csv"
            # Add 'Rank' to the fieldnames
            fieldnames = ['Event', 'Gender', 'Athlete', 'Rank', 'Mark', 'Event Date', 'DatePulled']
            
            # Create a 'results' directory if it doesn't exist
            os.makedirs('results', exist_ok=True)
            output_path = os.path.join('results', output_file)
            
            # Create the CSV file with headers if it doesn't exist
            if not os.path.exists(output_path):
                with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                print(f"Created new state rankings file: {output_path}")
            
            # Create state qualifying marks file
            qual_marks_file = f"State Meet Mark Requirements {today}.csv"
            qual_marks_path = os.path.join('results', qual_marks_file)
            
            # Create the qualifying marks CSV file with headers
            with open(qual_marks_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Event', 'Gender', 'Rank', 'Mark'])
            print(f"Created state qualifying marks file: {qual_marks_path}")
            
            # Process boys and girls rankings
            for gender in ["girls", "boys"]:
                gender_proper = gender.capitalize()  # Capitalize for output
                
                # Create the base URL
                base_url = f"https://co.milesplit.com/rankings/events/high-school-{gender}/outdoor-track-and-field"
                
                # Get appropriate events for this gender
                events = EVENT_TYPES["all"][:]  # Start with events for all genders
                
                # Add gender-specific events
                if gender == "boys":
                    events.extend(EVENT_TYPES["boysonly"])
                elif gender == "girls":
                    events.extend(EVENT_TYPES["girlsonly"])
                
                print(f"Processing {len(events)} events for {gender_proper}")
                
                # Process each event
                for event_name in events:
                    print(f"Processing event: {event_name}")
                    
                    # Construct the full URL
                    event_url = f"{base_url}/{event_name}?year={year}&accuracy=fat&league={league}"
                    print(f"URL: {event_url}")
                    
                    # Store results for this event
                    event_results = []
                    
                    # Get the first page
                    page_num = 1
                    has_more_pages = True
                    
                    # For qualifying marks tracking
                    top_mark = {'rank': None, 'mark': None}
                    last_qualifying_mark = {'rank': None, 'mark': None}
                    
                    while has_more_pages:
                        print(f"Processing page {page_num} for {gender_proper} {event_name}")
                        
                        # Respect rate limits
                        if page_num > 1:
                            time.sleep(0.25)  # Wait 250ms between pages to avoid ban
                        
                        # Navigate to the page
                        content = navigate_to_page_and_get_content(context, event_url)
                        
                        if not content:
                            print(f"Failed to get content for {event_url}")
                            break
                        
                        # Parse the page content
                        soup = BeautifulSoup(content, 'html.parser')
                        
                        # Find the data div
                        data_div = soup.select_one('div.data')
                        
                        if not data_div:
                            print(f"No data div found for {event_name}")
                            break
                        
                        # Find all rows in the tbody
                        rows = data_div.select('tbody tr')
                        
                        if not rows:
                            print(f"No rows found for {event_name}")
                            break
                        
                        print(f"Found {len(rows)} rows")
                        
                        # Capture qualifying marks on first page
                        if page_num == 1:
                            # Process state qualifying marks
                            for row in rows:
                                rank_td = row.select_one('td.rank')
                                if not rank_td:
                                    continue
                                
                                try:
                                    rank = int(rank_td.text.strip())
                                except (ValueError, TypeError):
                                    continue  # Skip if rank is not a valid integer
                                
                                time_td = row.select_one('td.time')
                                mark = time_td.text.strip() if time_td else ""
                                
                                if not mark:
                                    continue
                                
                                # Update top mark (rank 1)
                                if rank == 1:
                                    top_mark = {'rank': 1, 'mark': mark}
                                
                                # Update last qualifying mark (closest to 18 without going over)
                                if rank <= 18:
                                    last_qualifying_mark = {'rank': rank, 'mark': mark}
                            
                            # Write qualifying marks to CSV after processing first page
                            with open(qual_marks_path, 'a', newline='', encoding='utf-8') as csvfile:
                                writer = csv.writer(csvfile)
                                
                                # Write top mark (rank 1)
                                if top_mark['rank'] is not None:
                                    writer.writerow([
                                        event_name, 
                                        gender_proper, 
                                        top_mark['rank'], 
                                        top_mark['mark']
                                    ])
                                    print(f"Added top mark (rank 1) for {gender_proper} {event_name}: {top_mark['mark']}")
                                
                                # Write last qualifying mark (closest to 18 without going over)
                                if last_qualifying_mark['rank'] is not None and last_qualifying_mark['rank'] != 1:
                                    writer.writerow([
                                        event_name, 
                                        gender_proper, 
                                        last_qualifying_mark['rank'], 
                                        last_qualifying_mark['mark']
                                    ])
                                    print(f"Added last qualifying mark (rank {last_qualifying_mark['rank']}) for {gender_proper} {event_name}: {last_qualifying_mark['mark']}")
                                
                                if top_mark['rank'] is None and last_qualifying_mark['rank'] is None:
                                    print(f"No qualifying marks found for {gender_proper} {event_name}")
                        
                        # Process each row for school results
                        for row in rows:
                            # Check if the team is our target school
                            team_div = row.select_one('td.name div.team')
                            
                            if not team_div:
                                continue
                                
                            team_name = team_div.text.strip()
                            
                            if target_school not in team_name:
                                continue
                                
                            # Found a match for our school
                            print(f"Found ranking for {target_school}")
                            
                            # Extract rank
                            rank_td = row.select_one('td.rank')
                            rank = rank_td.text.strip() if rank_td else ""
                            
                            # Extract time/mark
                            time_td = row.select_one('td.time')
                            mark = time_td.text.strip() if time_td else ""
                            
                            # Extract athlete name
                            athlete_div = row.select_one('td.name div.athlete')
                            
                            if athlete_div and athlete_div.select_one('a'):
                                athlete_name = athlete_div.select_one('a').text.strip()
                            elif athlete_div:
                                athlete_name = athlete_div.text.strip()
                            else:
                                # This is likely a relay, use team name
                                athlete_name = f"{team_name} Relay"
                            
                            # Extract meet name and date
                            meet_td = row.select_one('td.meet')
                            
                            meet_name = ""
                            event_date = ""
                            
                            if meet_td:
                                meet_div = meet_td.select_one('div.meet a')
                                meet_name = meet_div.text.strip() if meet_div else ""
                                
                                date_div = meet_td.select_one('div.date time.start')
                                event_date = date_div.text.strip() if date_div else ""
                            
                            # Add result to the list
                            result = {
                                'Event': event_name,
                                'Gender': gender_proper,
                                'Athlete': athlete_name,
                                'Mark': mark,
                                'Rank': rank,
                                'Event Date': event_date,
                                'DatePulled': today
                            }
                            event_results.append(result)
                            all_results.append(result)
                        
                        # Check if there are more pages
                        pagination = soup.select_one('nav.pagination')
                        
                        if pagination and pagination.select_one('a.next'):
                            # There's a next page link
                            next_page_url = pagination.select_one('a.next')['href']
                            
                            if next_page_url.startswith('/'):
                                next_page_url = f"https://co.milesplit.com{next_page_url}"
                            
                            event_url = next_page_url
                            page_num += 1
                        else:
                            has_more_pages = False
                    
                    # After processing all pages for this event, append the results to the CSV
                    if event_results:
                        with open(output_path, 'a', newline='', encoding='utf-8') as csvfile:
                            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                            for result in event_results:
                                writer.writerow(result)
                        print(f"Appended {len(event_results)} results for {gender_proper} {event_name} to {output_path}")
                    else:
                        print(f"No results found for {gender_proper} {event_name}")
            
            # Final stats
            print(f"Completed state rankings scan. Total results: {len(all_results)}")
            return all_results
        
        finally:
            browser.close()

def main():
    """Main function to parse command-line arguments and run the script."""
    parser = argparse.ArgumentParser(description='Scrape MileSplit event results or state rankings.')
    
    # Define the command-line arguments
    parser.add_argument('--event', type=str, help='URL of the MileSplit event to scrape')
    parser.add_argument('--stateranks', action='store_true', help='Scrape state rankings data')
    
    # Parse the arguments
    args = parser.parse_args()
    
    # Load .env file
    load_dotenv()

    # Access variables
    username = os.getenv("USERNAME")
    password = os.getenv("PASSWORD")
    target_school = os.getenv("TARGET_SCHOOL", "Peak to Peak Charter School")  # Default if not set
    year = os.getenv("YEAR", "2025")  # Default if not set
    league = os.getenv("LEAGUE", "8691")  # Default if not set
    
    if not username or not password:
        print("Error: USERNAME and PASSWORD must be set in .env file")
        sys.exit(1)
        
    print(f"Target school: {target_school}")

    # Check which action to perform
    if args.event:
        # Process event results
        url = args.event
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
    
    elif args.stateranks:
        # Process state rankings
        results = get_state_ranks(target_school, username, password, year, league)
        # The function itself writes to CSV
    
    else:
        # No valid arguments provided, print help
        parser.print_help()

if __name__ == "__main__":
    main()