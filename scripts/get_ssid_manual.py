#!/usr/bin/env python3
"""
Simplified SSID extractor - opens browser, waits for manual login, then extracts SSID
"""
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import json
import re

try:
    from webdriver_manager.chrome import ChromeDriverManager
    service = Service(ChromeDriverManager().install())
except:
    service = None

chrome_options = Options()
chrome_options.add_argument('--start-maximized')
chrome_options.add_experimental_option("detach", True)  # Keep browser open
chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

if service:
    driver = webdriver.Chrome(service=service, options=chrome_options)
else:
    driver = webdriver.Chrome(options=chrome_options)

print("=" * 60)
print("PocketOption SSID Extractor (Manual Login)")
print("=" * 60)
print()
print("Browser will open. Please:")
print("1. Login to https://pocketoption.com/ manually")
print("2. Wait for the trading interface to load")
print("3. Press ENTER here when done")
print()
print("Opening browser...")
driver.get("https://pocketoption.com/login")

input("\nPress ENTER after you have logged in and the page has loaded...\n")

print("\n[*] Extracting SSID from WebSocket logs...")

# Wait a bit for WebSocket messages
time.sleep(5)

# Extract from performance logs
logs = driver.get_log('performance')
ssid = None

for log in logs:
    try:
        message = json.loads(log['message'])
        method = message.get('message', {}).get('method', '')
        params = message.get('message', {}).get('params', {})
        
        # Look for WebSocket messages
        if method == 'Network.webSocketFrameReceived':
            payload = params.get('response', {}).get('payloadData', '')
            if payload and '42["auth"' in payload:
                ssid = payload.strip()
                print("[OK] Found SSID in WebSocket received message!")
                break
        
        if method == 'Network.webSocketFrameSent':
            payload = params.get('request', {}).get('payloadData', '')
            if payload and '42["auth"' in payload:
                ssid = payload.strip()
                print("[OK] Found SSID in WebSocket sent message!")
                break
    except:
        continue

if not ssid:
    # Try from page source
    print("[*] Trying to extract from page source...")
    page_source = driver.page_source
    auth_pattern = r'42\["auth",\{[^}]+\}\]'
    matches = re.findall(auth_pattern, page_source)
    if matches:
        ssid = matches[0]
        print("[OK] Found SSID in page source!")

if ssid:
    print("\n" + "=" * 60)
    print("[OK] SSID EXTRACTED:")
    print("=" * 60)
    print(ssid)
    print("=" * 60)
    
    with open('ssid.txt', 'w', encoding='utf-8') as f:
        f.write(ssid)
    print("\n[*] Saved to ssid.txt")
else:
    print("\n[ERROR] Could not extract SSID")
    print("[*] Make sure you are logged in and the page is fully loaded")
    print("[*] Try refreshing the page and waiting a few seconds")

print("\n[*] Browser will stay open for 10 more seconds...")
time.sleep(10)
driver.quit()

