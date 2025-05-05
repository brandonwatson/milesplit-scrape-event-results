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
# - add "date pulled" to the State Meet Mark Requirements CSV - FIXED
# - remove "Finals" from event names when getting the data (before it get's to CSV)
# - add a "--debug" flag to save screenshots and HTML for debugging purposes, and not have this be default behavior

# EXPERIMENT BEING RUN
# - test running with a sleep=.1 and not .25

# Define the tracked `Panic Index` track meets
PANIC_INDEX_MEETS = {
    "Cardinal Inivtational" : "https://co.milesplit.com/meets/652527-cardinal-invitational-2025",
    "Strasburg Dave Spiller" : "https://co.milesplit.com/meets/654034-strasburg-dave-spiller-invitational-postponed-to-may-5-2025",
    "Centauri Invitational 2025" : "https://co.milesplit.com/meets/654392-centauri-invitational-canceled-2025",
    "Spartan Last Chance Qualifier" : "https://co.milesplit.com/meets/636625-spartan-last-chance-qualifier-2025",
    "Delta Twighlight 2025" : "https://co.milesplit.com/meets/660142-delta-twilight-2025",
    "Monte Vista Last Chance" : "https://co.milesplit.com/meets/652252-2025-monte-vista-last-chance-invitational-2025",
    "Friday Night Lights" : "https://co.milesplit.com/meets/636094-friday-night-lights-2025",
    "Hoka St Vrain" : "https://co.milesplit.com/meets/651208-hoka-st-vrain-invitational-2025",
    "Joe Shields Invitational" : "https://co.milesplit.com/meets/651085-joe-shields-invitational-2025",
    "Trojan Horse Invite" : "https://co.milesplit.com/meets/654965-trojan-horse-invite-sneak-into-the-state-meet-2025",
    "Windjammer Track Classic" : "https://co.milesplit.com/meets/649954-windjammer-track-classic-2025",
    "Maxine Erhmann Thornton" : "https://co.milesplit.com/meets/646969-maxine-erhmann-thornton-invite-2025",
    "Montrose Invitational" : "https://co.milesplit.com/meets/651090-montrose-invitational-2025",
    "Rumble on the Divide" : "https://co.milesplit.com/meets/680880-rumble-on-the-divide-2025",
    "Teddy's Last Chance" : "https://co.milesplit.com/meets/638820-teddys-last-chance-qualifier-2025"
}

PANIC_INDEX_EVENTS = [
    "Girls LJ",
    "Girls TJ",
    "Girls D",
    "Girls S",
    "Girls PV",
    "Girls 4x200m",
    "Boys D",
    "Boys LJ",
    "Boys PV",
    "Boys 200m",
    "Boys 400m",
    "Boys 4x200m",
    "Boys 4x400m",
]

# Define the event types structure with dictionary for long names
EVENT_TYPES = {
    "100m": {"long_name": "100 Meter Dash Finals", "female_event": True, "male_event": True},
    "200m": {"long_name": "200 Meter Dash Finals", "female_event": True, "male_event": True},
    "400m": {"long_name": "400 Meter Dash Finals", "female_event": True, "male_event": True},
    "300H": {"long_name": "300 Meter Hurdles Finals", "female_event": True, "male_event": True},
    "800m": {"long_name": "800 Meter Run Finals", "female_event": True, "male_event": True},
    "1600m": {"long_name": "1600 Meter Run Finals", "female_event": True, "male_event": True},
    "3200m": {"long_name": "3200 Meter Run Finals", "female_event": True, "male_event": True},
    "D": {"long_name": "Discus Finals", "female_event": True, "male_event": True},
    "S": {"long_name": "Shot Put Finals", "female_event": True, "male_event": True},
    "HJ": {"long_name": "High Jump Finals", "female_event": True, "male_event": True},
    "TJ": {"long_name": "Triple Jump Finals", "female_event": True, "male_event": True},
    "LJ": {"long_name": "Long Jump Finals", "female_event": True, "male_event": True},
    "PV": {"long_name": "Pole Vault Finals", "female_event": True, "male_event": True},
    "4x100m": {"long_name": "4x100 Meter Relay", "female_event": True, "male_event": True},
    "4x200m": {"long_name": "4x200 Meter Relay", "female_event": True, "male_event": True},
    "4x400m": {"long_name": "4x400 Meter Relay", "female_event": True, "male_event": True},
    "4x800m": {"long_name": "4x800 Meter Relay", "female_event": True, "male_event": True},
    "110H": {"long_name": "110 Meter Hurdles Finals", "female_event": False, "male_event": True},
    "100H": {"long_name": "100 Meter Hurdles Finals", "female_event": True, "male_event": False}
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
    """Standardize the URL format but preserve any path components after 'results/'."""
    match = re.search(r'/meets/(\d+)(?:-[^/]+)?/results(.*)', url)
    if match:
        meet_id = match.group(1)
        results_suffix = match.group(2) or ""  # The part after "results" (might be empty)
        return f"https://co.milesplit.com/meets/{meet_id}/results{results_suffix}"
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
        page.goto('https://co.milesplit.com/', wait_until="dom" \
        "content" \
        "loaded", timeout=30000)
        
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
                writer.writerow(['Event', 'Gender', 'Rank', 'Mark', 'DatePulled'])
            print(f"Created state qualifying marks file: {qual_marks_path}")
            
            # Process boys and girls rankings
            for gender in ["girls", "boys"]:
                gender_proper = gender.capitalize()  # Capitalize for output
                
                # Create the base URL
                base_url = f"https://co.milesplit.com/rankings/events/high-school-{gender}/outdoor-track-and-field"
                
                # Get appropriate events for this gender
                events = []
                
                # Add events based on gender
                for event_short, event_info in EVENT_TYPES.items():
                    if gender == "boys" and event_info["male_event"]:
                        events.append(event_short)
                    elif gender == "girls" and event_info["female_event"]:
                        events.append(event_short)
                
                print(f"Processing {len(events)} events for {gender_proper}")
                
                # Process each event
                for event_short in events:
                    print(f"Processing event: {event_short}")
                    
                    # Get the long name for this event
                    event_long_name = EVENT_TYPES[event_short]["long_name"]
                    
                    # Construct the full URL
                    event_url = f"{base_url}/{event_short}?year={year}&accuracy=fat&league={league}"
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
                        print(f"Processing page {page_num} for {gender_proper} {event_short}")
                        
                        # Respect rate limits
                        if page_num > 1:
                            time.sleep(0.1)  # Wait 100ms between pages to avoid ban
                        
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
                            print(f"No data div found for {event_short}")
                            break
                        
                        # Find all rows in the tbody
                        rows = data_div.select('tbody tr')
                        
                        if not rows:
                            print(f"No rows found for {event_short}")
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
                                        event_long_name, 
                                        gender_proper, 
                                        top_mark['rank'], 
                                        top_mark['mark'],
                                        today
                                    ])
                                    print(f"Added top mark (rank 1) for {gender_proper} {event_long_name}: {top_mark['mark']}")
                                
                                # Write last qualifying mark (closest to 18 without going over)
                                if last_qualifying_mark['rank'] is not None and last_qualifying_mark['rank'] != 1:
                                    writer.writerow([
                                        event_long_name, 
                                        gender_proper, 
                                        last_qualifying_mark['rank'], 
                                        last_qualifying_mark['mark'],
                                        today
                                    ])
                                    print(f"Added last qualifying mark (rank {last_qualifying_mark['rank']}) for {gender_proper} {event_long_name}: {last_qualifying_mark['mark']}")
                                
                                if top_mark['rank'] is None and last_qualifying_mark['rank'] is None:
                                    print(f"No qualifying marks found for {gender_proper} {event_long_name}")
                        
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
                                'Event': event_short,  # Use short form name instead of long form
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
                        print(f"Appended {len(event_results)} results for {gender_proper} {event_long_name} to {output_path}")
                    else:
                        print(f"No results found for {gender_proper} {event_long_name}")
            
            # Final stats
            print(f"Completed state rankings scan. Total results: {len(all_results)}")
            return all_results
        
        finally:
            browser.close()

def get_panic_index_athlete_participation(username, password, year, league):
    """Get athlete participation data for the panic index meets."""
    print("Getting panic index athlete participation data...")
    
    with sync_playwright() as playwright:
        # Login with Playwright
        login_result = login_with_playwright(playwright, username, password)
        if not login_result:
            print("Failed to login for panic index athlete participation")
            return
            
        browser, context = login_result
        
        try:
            today = date.today().strftime("%Y-%m-%d")  # Format date as YYYY-MM-DD
            
            # Create the output file path
            output_file = f"panic_index_athlete_participation-{today}.csv"
            fieldnames = ['Meet Name', 'Meet Date', 'Registration Status', 'Athlete School', 'Athlete Name', 'Gender', 'Event Name']
            
            # Create a 'results' directory if it doesn't exist
            os.makedirs('results', exist_ok=True)
            output_path = os.path.join('results', output_file)
            
            # Create the CSV file with headers
            with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
            
            print(f"Created new panic index athlete participation file: {output_path}")
            
            # Process each meet in the panic index
            for meet_name, meet_url in PANIC_INDEX_MEETS.items():
                print(f"Processing meet: {meet_name}")
                
                # Get the main meet page to extract date and registration status
                main_content = navigate_to_page_and_get_content(context, meet_url)
                
                if not main_content:
                    print(f"Failed to get content for {meet_url}")
                    continue
                
                # Parse the main page
                main_soup = BeautifulSoup(main_content, 'html.parser')
                
                # Extract meet date
                meet_date = ""
                date_elem = main_soup.select_one('div.basicInfo div.date time')
                if date_elem:
                    meet_date = date_elem.text.strip()
                
                # Extract registration status
                registration_status = "Closed"  # Default
                countdown_div = main_soup.select_one('div.basicInfo div.countDown')
                if countdown_div and countdown_div.get_text(strip=True):
                    registration_status = "Open"
                
                print(f"Meet Date: {meet_date}, Registration Status: {registration_status}")
                
                # Construct entries URL
                entries_url = f"{meet_url}/entries"
                
                # Get the entries page
                entries_content = navigate_to_page_and_get_content(context, entries_url)
                
                if not entries_content:
                    print(f"Failed to get content for {entries_url}")
                    continue
                
                # Parse the entries page
                entries_soup = BeautifulSoup(entries_content, 'html.parser')
                
                # Find the results section
                results_section = entries_soup.select_one('section#results')
                
                if not results_section:
                    print(f"No results section found for {meet_name}")
                    continue
                
                # Find all tables in the results section
                tables = results_section.select('table')
                
                if not tables:
                    print(f"No tables found for {meet_name}")
                    continue
                
                print(f"Found {len(tables)} tables")
                
                # Process each table
                for table in tables:
                    # Get event name directly from table data-event attribute
                    event_name_full = table.get('data-event', '')
                    
                    if not event_name_full:
                        # Fallback to H3 in the table header if data-event is not available
                        event_header = table.select_one('thead tr th h3')
                        if event_header:
                            event_name_full = event_header.text.split('<span')[0].strip()
                        else:
                            print("Could not find event name for a table")
                            continue
                    
                    print(f"Processing event: {event_name_full}")
                    
                    # Determine gender from event name
                    gender = ""
                    if "Boys" in event_name_full or "Men" in event_name_full:
                        gender = "Boys"
                    elif "Girls" in event_name_full or "Women" in event_name_full:
                        gender = "Girls"
                    else:
                        print(f"Could not determine gender from event name: {event_name_full}")
                        continue
                    
                    # Extract short event name
                    event_name = event_name_full
                    for prefix in ["HS Boys ", "HS Girls ", "Boys ", "Girls ", "Men's ", "Women's "]:
                        event_name = event_name.replace(prefix, "")
                    
                    # Find corresponding short name for the event
                    short_event_name = None
                    for short_name, event_info in EVENT_TYPES.items():
                        # Check if the long name is in the event name
                        long_name = event_info["long_name"].replace(" Finals", "")
                        if long_name in event_name or event_name in long_name:
                            short_event_name = short_name
                            break
                    
                    if not short_event_name:
                        # Try additional parsing for common event names
                        if "100 Meter" in event_name and "Hurdle" not in event_name:
                            short_event_name = "100m"
                        elif "200 Meter" in event_name:
                            short_event_name = "200m"
                        elif "400 Meter" in event_name and "Relay" not in event_name:
                            short_event_name = "400m"
                        elif "800 Meter" in event_name:
                            short_event_name = "800m"
                        elif "1600 Meter" in event_name:
                            short_event_name = "1600m"
                        elif "3200 Meter" in event_name:
                            short_event_name = "3200m"
                        elif "Discus" in event_name:
                            short_event_name = "D"
                        elif "Shot Put" in event_name:
                            short_event_name = "S"
                        elif "High Jump" in event_name:
                            short_event_name = "HJ"
                        elif "Long Jump" in event_name:
                            short_event_name = "LJ"
                        elif "Triple Jump" in event_name:
                            short_event_name = "TJ"
                        elif "Pole Vault" in event_name:
                            short_event_name = "PV"
                        elif "4x100" in event_name:
                            short_event_name = "4x100m"
                        elif "4x200" in event_name:
                            short_event_name = "4x200m"
                        elif "4x400" in event_name:
                            short_event_name = "4x400m"
                        elif "4x800" in event_name:
                            short_event_name = "4x800m"
                        elif "110 Meter Hurdle" in event_name:
                            short_event_name = "110H"
                        elif "100 Meter Hurdle" in event_name:
                            short_event_name = "100H"
                        elif "300 Meter Hurdle" in event_name:
                            short_event_name = "300H"
                    
                    if not short_event_name:
                        print(f"Could not determine short event name for: {event_name}")
                        continue
                    
                    # Check if this event is in our PANIC_INDEX_EVENTS list
                    event_key = f"{gender} {short_event_name}"
                    if event_key not in PANIC_INDEX_EVENTS:
                        print(f"Skipping event {event_key} - not in PANIC_INDEX_EVENTS")
                        continue
                    
                    # Find all rows in the table
                    rows = table.select('tbody tr')
                    
                    print(f"Found {len(rows)} athletes in {event_name_full}")
                    
                    # Process each row
                    for row in rows:
                        # Extract athlete name
                        athlete_td = row.select_one('td:nth-child(1)')
                        if not athlete_td or not athlete_td.select_one('a'):
                            continue
                            
                        athlete_name = athlete_td.select_one('a').text.strip()
                        first_name = athlete_name.split(",")[1]
                        last_name = athlete_name.split(",")[0]
                        athlete_name = f"{first_name.strip()} {last_name.strip()}"
                        
                        # Extract school name
                        school_td = row.select_one('td:nth-child(3)')
                        if not school_td or not school_td.select_one('a'):
                            continue
                            
                        school_name = school_td.select_one('a').text.strip()
                        
                        # Write to CSV
                        with open(output_path, 'a', newline='', encoding='utf-8') as csvfile:
                            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                            writer.writerow({
                                'Meet Name': meet_name,
                                'Meet Date': meet_date,
                                'Registration Status': registration_status,
                                'Athlete School': school_name,
                                'Athlete Name': athlete_name,
                                'Gender': gender,
                                'Event Name': short_event_name
                            })
                
                # Respect rate limits
                time.sleep(0.1)  # Wait 100ms between meets to avoid ban
            
            print(f"Completed panic index athlete participation scan. Results written to {output_path}")
        
        finally:
            browser.close()

def get_panic_index_state_ranks(username, password, year, league):
    """Get state rankings for panic index events (ranks 10-50 from first page only)."""
    print("Getting panic index state rankings data...")
    
    with sync_playwright() as playwright:
        # Login with Playwright
        login_result = login_with_playwright(playwright, username, password)
        if not login_result:
            print("Failed to login for panic index state rankings")
            return
            
        browser, context = login_result
        
        try:
            today = date.today().strftime("%Y-%m-%d")  # Format date as YYYY-MM-DD
            
            # Create the output file path
            output_file = f"panic_index_state_ranks-{today}.csv"
            fieldnames = ['School Name', 'Athlete Name', 'Event', 'Gender', 'Rank']
            
            # Create a 'results' directory if it doesn't exist
            os.makedirs('results', exist_ok=True)
            output_path = os.path.join('results', output_file)
            
            # Create the CSV file with headers
            with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
            
            print(f"Created new panic index state rankings file: {output_path}")
            
            # Process each event in the panic index
            for event_str in PANIC_INDEX_EVENTS:
                parts = event_str.split()
                gender = parts[0]  # "Boys" or "Girls"
                event_code = parts[1]  # The event code like "LJ", "D", etc.
                
                print(f"Processing {event_str}")
                
                # Convert gender to lowercase for URL
                gender_lower = gender.lower()
                
                # Construct the URL
                url = f"https://co.milesplit.com/rankings/events/high-school-{gender_lower}/outdoor-track-and-field/{event_code}?year={year}&accuracy=fat&league={league}"
                
                print(f"URL: {url}")
                
                # Get the page content
                content = navigate_to_page_and_get_content(context, url)
                
                if not content:
                    print(f"Failed to get content for {url}")
                    continue
                
                # Parse the page
                soup = BeautifulSoup(content, 'html.parser')
                
                # Find the data div
                data_div = soup.select_one('div.data')
                
                if not data_div:
                    print(f"No data div found for {event_str}")
                    continue
                
                # Find all rows in the tbody
                rows = data_div.select('tbody tr')
                
                if not rows:
                    print(f"No rows found for {event_str}")
                    continue
                
                print(f"Found {len(rows)} rows")
                
                # Process each row (only ranks 10-50)
                for row in rows:
                    rank_td = row.select_one('td.rank')
                    if not rank_td:
                        continue
                    
                    try:
                        rank = int(rank_td.text.strip())
                    except (ValueError, TypeError):
                        continue  # Skip if rank is not a valid integer
                    
                    # Only include ranks 10-50
                    if rank < 10:
                        continue
                    
                    # Extract school name
                    team_div = row.select_one('td.name div.team')
                    if not team_div:
                        continue
                        
                    school_name = team_div.text.strip()
                    
                    # Extract athlete name
                    athlete_div = row.select_one('td.name div.athlete')
                    
                    if athlete_div and athlete_div.select_one('a'):
                        athlete_name = athlete_div.select_one('a').text.strip()
                    elif athlete_div:
                        athlete_name = athlete_div.text.strip()
                    else:
                        # This is likely a relay, use school name
                        athlete_name = f"{school_name} Relay"
                    
                    # Write to CSV
                    with open(output_path, 'a', newline='', encoding='utf-8') as csvfile:
                        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                        writer.writerow({
                            'School Name': school_name,
                            'Athlete Name': athlete_name,
                            'Event': event_code,  # Use short form event name
                            'Gender': gender,
                            'Rank': str(rank)
                        })
                
                # Respect rate limits
                time.sleep(0.1)  # Wait 100ms between events to avoid ban
            
            print(f"Completed panic index state rankings scan. Results written to {output_path}")
        
        finally:
            browser.close()

def main():
    """Main function to parse command-line arguments and run the script."""
    parser = argparse.ArgumentParser(description='Scrape MileSplit event results or state rankings.')
    
    # Define the command-line arguments
    parser.add_argument('--event', type=str, help='URL of the MileSplit event to scrape')
    parser.add_argument('--stateranks', action='store_true', help='Scrape state rankings data')
    parser.add_argument('--panicindex', action='store_true', help='Generate panic index data')
    
    # Parse the arguments
    args = parser.parse_args()
    
    # Load .env file
    load_dotenv()

    # Access variables
    username = os.getenv("USERNAME")
    password = os.getenv("PASSWORD")
    target_school = os.getenv("TARGET_SCHOOL", "Peak to Peak Charter School")  # Default if not set
    year = os.getenv("YEAR", "2025")  # Default if not set
    league = os.getenv("LEAGUE", "9123")  # Default if not set; previously had 8691 as the league
    
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
    
    elif args.panicindex:
        # Process panic index data
        print("Processing panic index data...")
        get_panic_index_athlete_participation(username, password, year, league)
        get_panic_index_state_ranks(username, password, year, league)
    
    else:
        # No valid arguments provided, print help
        parser.print_help()

if __name__ == "__main__":
    main()