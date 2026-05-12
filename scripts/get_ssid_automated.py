#!/usr/bin/env python3
"""
Automated SSID retrieval using Selenium
Logs into PocketOption and extracts SSID from WebSocket connection
"""
import asyncio
import json
import re
import time
from typing import Optional

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False
    print("⚠️ Selenium not installed. Installing...")
    import subprocess
    import sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "selenium", "webdriver-manager"])
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    HAS_SELENIUM = True


def setup_chrome_driver(headless: bool = True):
    """Setup Chrome driver with options"""
    chrome_options = Options()
    if headless:
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--headless=new')  # New headless mode
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36')
    
    # Enable performance logging to capture WebSocket messages
    chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    
    try:
        # Try to use webdriver-manager for automatic driver management
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
        except:
            # Try chromium-browser on Linux
            try:
                chrome_options.binary_location = '/usr/bin/chromium-browser'
                driver = webdriver.Chrome(options=chrome_options)
            except:
                # Fallback to system Chrome/Chromium
                driver = webdriver.Chrome(options=chrome_options)
    except Exception as e:
        print(f"⚠️ Error setting up Chrome: {e}")
        print("   Trying with chromium-browser...")
        chrome_options.binary_location = '/usr/bin/chromium-browser'
        driver = webdriver.Chrome(options=chrome_options)
    
    return driver


def extract_ssid_from_logs(driver) -> Optional[str]:
    """Extract SSID from Chrome performance logs (WebSocket messages)"""
    logs = driver.get_log('performance')
    
    for log in logs:
        try:
            message = json.loads(log['message'])
            method = message.get('message', {}).get('method', '')
            params = message.get('message', {}).get('params', {})
            
            # Look for WebSocket messages
            if method == 'Network.webSocketFrameReceived':
                payload = params.get('response', {}).get('payloadData', '')
                if payload and '42["auth"' in payload:
                    print(f"✅ Found SSID in WebSocket message!")
                    return payload.strip()
            
            # Also check for WebSocket sent messages
            if method == 'Network.webSocketFrameSent':
                payload = params.get('request', {}).get('payloadData', '')
                if payload and '42["auth"' in payload:
                    print(f"✅ Found SSID in WebSocket sent message!")
                    return payload.strip()
        except:
            continue
    
    return None


def extract_ssid_from_storage(driver) -> Optional[str]:
    """Extract SSID from localStorage or sessionStorage"""
    try:
        # Try localStorage
        storage_data = driver.execute_script("return localStorage.getItem('session') || localStorage.getItem('ssid') || sessionStorage.getItem('session') || sessionStorage.getItem('ssid');")
        if storage_data:
            return storage_data
    except:
        pass
    
    # Try to get from cookies
    try:
        cookies = driver.get_cookies()
        for cookie in cookies:
            if 'session' in cookie.get('name', '').lower() or 'ssid' in cookie.get('name', '').lower():
                return cookie.get('value', '')
    except:
        pass
    
    return None


def get_ssid_from_pocketoption(email: str, password: str, headless: bool = True) -> Optional[str]:
    """
    Login to PocketOption and extract SSID
    
    Args:
        email: Email for login
        password: Password for login
        headless: Run browser in headless mode
    
    Returns:
        SSID string or None
    """
    driver = None
    try:
        print("[*] Starting browser...")
        driver = setup_chrome_driver(headless=headless)
        
        print("[*] Navigating to PocketOption...")
        driver.get("https://pocketoption.com/")
        time.sleep(3)
        
        # Wait for and click login button
        print("[*] Looking for login button...")
        try:
            # Try different possible selectors for login button
            login_selectors = [
                "//a[contains(text(), 'Log in')]",
                "//a[contains(text(), 'Войти')]",
                "//button[contains(text(), 'Log in')]",
                "//button[contains(text(), 'Войти')]",
                "//a[@href='/login']",
                ".login-button",
                "#login-button",
            ]
            
            login_clicked = False
            for selector in login_selectors:
                try:
                    if selector.startswith("//") or selector.startswith(".//"):
                        element = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, selector))
                        )
                    else:
                        element = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                        )
                    element.click()
                    login_clicked = True
                    print(f"[OK] Clicked login using selector: {selector}")
                    break
                except:
                    continue
            
            if not login_clicked:
                print("[!] Could not find login button, trying direct login URL...")
                driver.get("https://pocketoption.com/login")
            
            time.sleep(2)
        except Exception as e:
            print(f"[!] Could not click login button: {e}")
            print("   Trying direct login URL...")
            driver.get("https://pocketoption.com/login")
            time.sleep(2)
        
        # Fill in login form
        print("[*] Filling login form...")
        try:
            # Wait for page to load completely
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            time.sleep(2)
            
            # Debug: Print page structure
            if not headless:
                print("   [DEBUG] Page structure:")
                print(f"      Title: {driver.title}")
                print(f"      URL: {driver.current_url}")
                # Count inputs
                all_inputs = driver.find_elements(By.TAG_NAME, "input")
                print(f"      Total inputs found: {len(all_inputs)}")
                for inp in all_inputs[:5]:  # Show first 5
                    inp_type = inp.get_attribute("type") or "text"
                    inp_name = inp.get_attribute("name") or ""
                    print(f"         - {inp_type} input, name='{inp_name}'")
            
            # Try to find email field with multiple strategies
            print("   [*] Looking for email field...")
            email_field = None
            
            # Strategy 1: Try common selectors
            email_selectors = [
                ("css", "input[type='email']"),
                ("css", "input[name='email']"),
                ("css", "input[name='username']"),
                ("css", "input[name='login']"),
                ("css", "input[id*='email']"),
                ("css", "input[id*='login']"),
                ("css", "input[placeholder*='email' i]"),
                ("css", "input[placeholder*='Email' i]"),
                ("css", "#email"),
                ("css", "#username"),
                ("css", "#login"),
                ("xpath", "//input[@type='email']"),
                ("xpath", "//input[contains(@name, 'email') or contains(@name, 'login') or contains(@name, 'username')]"),
                ("xpath", "//input[contains(@placeholder, 'email') or contains(@placeholder, 'Email')]"),
            ]
            
            for method, selector in email_selectors:
                try:
                    if method == "css":
                        email_field = WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                    else:
                        email_field = WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.XPATH, selector))
                        )
                    if email_field and email_field.is_displayed():
                        print(f"   [OK] Found email field using: {selector}")
                        break
                except:
                    continue
            
            if not email_field:
                # Last resort: find any input that might be email
                print("   [!] Trying to find any input field...")
                inputs = driver.find_elements(By.TAG_NAME, "input")
                for inp in inputs:
                    inp_type = inp.get_attribute("type") or ""
                    inp_name = inp.get_attribute("name") or ""
                    if inp_type in ["email", "text"] and any(keyword in inp_name.lower() for keyword in ["email", "login", "user"]):
                        if inp.is_displayed():
                            email_field = inp
                            print(f"   [OK] Found email field by type/name: {inp_type}/{inp_name}")
                            break
            
            if not email_field:
                raise Exception("Could not find email field")
            
            # Fill email using JavaScript (more reliable)
            print("   [*] Filling email field...")
            try:
                driver.execute_script("arguments[0].value = arguments[1];", email_field, email)
                driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", email_field)
                driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", email_field)
                print(f"   [OK] Email set via JavaScript: {email}")
            except:
                # Fallback to normal method
                driver.execute_script("arguments[0].scrollIntoView(true);", email_field)
                time.sleep(0.5)
                email_field.click()
                time.sleep(0.5)
                email_field.clear()
                time.sleep(0.3)
                email_field.send_keys(email)
                print(f"   [OK] Email entered normally: {email}")
            time.sleep(1)
            
            # Find password field
            print("   [*] Looking for password field...")
            password_field = None
            
            password_selectors = [
                ("css", "input[type='password']"),
                ("css", "input[name='password']"),
                ("css", "input[name='pass']"),
                ("css", "input[id*='password']"),
                ("css", "input[id*='pass']"),
                ("css", "#password"),
                ("xpath", "//input[@type='password']"),
                ("xpath", "//input[contains(@name, 'password') or contains(@name, 'pass')]"),
            ]
            
            for method, selector in password_selectors:
                try:
                    if method == "css":
                        password_field = WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                    else:
                        password_field = WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.XPATH, selector))
                        )
                    if password_field and password_field.is_displayed():
                        print(f"   [OK] Found password field using: {selector}")
                        break
                except:
                    continue
            
            if not password_field:
                # Last resort
                inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
                if inputs:
                    password_field = inputs[0]
                    print("   [OK] Found password field (first password input)")
            
            if not password_field:
                raise Exception("Could not find password field")
            
            # Fill password using JavaScript (more reliable)
            print("   [*] Filling password field...")
            try:
                driver.execute_script("arguments[0].value = arguments[1];", password_field, password)
                driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", password_field)
                driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", password_field)
                print("   [OK] Password set via JavaScript")
            except:
                # Fallback to normal method
                driver.execute_script("arguments[0].scrollIntoView(true);", password_field)
                time.sleep(0.5)
                password_field.click()
                time.sleep(0.5)
                password_field.clear()
                time.sleep(0.3)
                password_field.send_keys(password)
                print("   [OK] Password entered normally")
            time.sleep(1)
            
            # Verify fields are filled
            email_value = driver.execute_script("return arguments[0].value;", email_field)
            if email_value != email:
                print(f"   [!] Email field value mismatch: expected '{email}', got '{email_value}'")
                # Try again
                driver.execute_script("arguments[0].value = ''; arguments[0].value = arguments[1];", email_field, email)
            
            password_value = driver.execute_script("return arguments[0].value;", password_field)
            if not password_value:
                print("   [!] Password field is empty, trying again...")
                driver.execute_script("arguments[0].value = arguments[1];", password_field, password)
            
            # Find and click submit button
            print("   [*] Looking for submit button...")
            submit_btn = None
            
            submit_selectors = [
                ("css", "button[type='submit']"),
                ("css", "input[type='submit']"),
                ("css", "button.btn-primary"),
                ("css", "button.btn-login"),
                ("css", ".submit-button"),
                ("css", ".login-button"),
                ("xpath", "//button[contains(text(), 'Log in') or contains(text(), 'Войти') or contains(text(), 'Login')]"),
                ("xpath", "//button[@type='submit']"),
                ("xpath", "//input[@type='submit']"),
                ("xpath", "//button[contains(@class, 'submit') or contains(@class, 'login')]"),
            ]
            
            for method, selector in submit_selectors:
                try:
                    if method == "css":
                        submit_btn = WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                        )
                    else:
                        submit_btn = WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.XPATH, selector))
                        )
                    if submit_btn and submit_btn.is_displayed():
                        print(f"   [OK] Found submit button using: {selector}")
                        break
                except:
                    continue
            
            if not submit_btn:
                # Try to find any button near the form
                print("   [!] Trying to find any submit button...")
                buttons = driver.find_elements(By.TAG_NAME, "button")
                for btn in buttons:
                    btn_text = btn.text.lower()
                    btn_type = btn.get_attribute("type") or ""
                    if btn_type == "submit" or any(keyword in btn_text for keyword in ["log", "login", "войти", "вход"]):
                        if btn.is_displayed():
                            submit_btn = btn
                            print(f"   [OK] Found submit button by text/type: {btn_text}/{btn_type}")
                            break
            
            if not submit_btn:
                # Last resort: try submitting form directly or Enter key
                print("   [!] Submit button not found, trying form submit...")
                try:
                    # Try to find form and submit it
                    form = password_field.find_element(By.XPATH, "./ancestor::form")
                    driver.execute_script("arguments[0].submit();", form)
                    print("   [OK] Form submitted via JavaScript")
                except:
                    # Try Enter key
                    from selenium.webdriver.common.keys import Keys
                    password_field.send_keys(Keys.RETURN)
                    print("   [OK] Pressed Enter key")
                time.sleep(3)
            else:
                driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
                time.sleep(0.5)
                # Try JavaScript click first (more reliable)
                try:
                    driver.execute_script("arguments[0].click();", submit_btn)
                    print("   [OK] Submit clicked (JavaScript)")
                except:
                    try:
                        submit_btn.click()
                        print("   [OK] Submit clicked (normal)")
                    except Exception as e:
                        print(f"   [!] Click failed: {e}, trying form submit...")
                        form = submit_btn.find_element(By.XPATH, "./ancestor::form")
                        driver.execute_script("arguments[0].submit();", form)
                        print("   [OK] Form submitted as fallback")
            
            # Wait for login to complete
            print("[*] Waiting for login to complete...")
            
            # Wait and check for navigation or errors
            for i in range(10):  # Check every second for 10 seconds
                time.sleep(1)
                current_url = driver.current_url
                
                # Check for errors
                try:
                    error_selectors = [
                        ".error", ".alert-danger", ".alert-error",
                        "[class*='error']", "[class*='Error']",
                        "div[role='alert']", ".notification-error"
                    ]
                    for selector in error_selectors:
                        error_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        for err in error_elements:
                            if err.is_displayed():
                                error_text = err.text.strip()
                                if error_text:
                                    print(f"   [!] Error message: {error_text}")
                                    break
                except:
                    pass
                
                # Check if URL changed (login successful)
                if 'login' not in current_url.lower():
                    print(f"   [OK] URL changed to: {current_url}")
                    print("   [OK] Login appears successful!")
                    break
                
                if i == 9:
                    print(f"   [!] Still on login page after 10 seconds: {current_url}")
                    # Take screenshot for debugging
                    try:
                        screenshot_path = "login_debug.png"
                        driver.save_screenshot(screenshot_path)
                        print(f"   [*] Screenshot saved: {screenshot_path}")
                    except:
                        pass
                    
                    # Check if form is still there
                    try:
                        form_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='email'], input[type='text']")
                        if form_inputs:
                            email_val = driver.execute_script("return arguments[0].value;", form_inputs[0])
                            print(f"   [DEBUG] Email field value: '{email_val}'")
                            if not email_val:
                                print("   [!] Email field is empty - form may not have been filled")
                    except:
                        pass
            
        except Exception as e:
            print(f"❌ Error during login: {e}")
            import traceback
            traceback.print_exc()
            return None
        
        # Wait for WebSocket connection to be established
        print("[*] Waiting for WebSocket connection...")
        time.sleep(5)
        
        # Try to extract SSID from various sources
        print("[*] Extracting SSID...")
        
        # Method 1: From performance logs
        ssid = extract_ssid_from_logs(driver)
        if ssid:
            print("[OK] SSID extracted from WebSocket logs!")
            return ssid
        
        # Method 2: From storage
        ssid = extract_ssid_from_storage(driver)
        if ssid:
            print("[OK] SSID extracted from storage!")
            return ssid
        
        # Method 3: Try to get from page source or JavaScript variables
        try:
            # Execute JavaScript to get SSID if stored in window object
            ssid = driver.execute_script("""
                return window.sessionId || 
                       window.ssid || 
                       window.SSID ||
                       (window.io && window.io.id) ||
                       null;
            """)
            if ssid:
                print("[OK] SSID extracted from JavaScript variables!")
                return ssid
        except:
            pass
        
        # Method 4: Look for auth messages in page source
        page_source = driver.page_source
        auth_pattern = r'42\["auth",\{[^}]+\}\]'
        matches = re.findall(auth_pattern, page_source)
        if matches:
            print("[OK] SSID found in page source!")
            return matches[0]
        
        print("[!] Could not extract SSID automatically")
        print("[*] Try running in non-headless mode to see what's happening:")
        print("   get_ssid_automated.py --no-headless")
        
        return None
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if driver:
            print("[*] Closing browser...")
            driver.quit()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Get SSID from PocketOption')
    parser.add_argument('--email', default='krekc4s@mail.ru', help='Email for login')
    parser.add_argument('--password', default='Vtapketrade', help='Password for login')
    parser.add_argument('--no-headless', action='store_true', help='Run browser in visible mode')
    parser.add_argument('--output', help='Save SSID to file')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("PocketOption SSID Extractor")
    print("=" * 60)
    print(f"Email: {args.email}")
    print(f"Headless: {not args.no_headless}")
    print("=" * 60)
    print()
    
    ssid = get_ssid_from_pocketoption(args.email, args.password, headless=not args.no_headless)
    
    if ssid:
        print("\n" + "=" * 60)
        print("[OK] SSID EXTRACTED:")
        print("=" * 60)
        print(ssid)
        print("=" * 60)
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(ssid)
            print(f"\n[*] Saved to {args.output}")
        
        # Also save to a default location
        with open('ssid.txt', 'w', encoding='utf-8') as f:
            f.write(ssid)
        print("[*] Also saved to ssid.txt")
        
        return 0
    else:
        print("\n[ERROR] Failed to extract SSID")
        print("\n[*] Tips:")
        print("   1. Try running with --no-headless to see what's happening")
        print("   2. Check if login credentials are correct")
        print("   3. Make sure Chrome/Chromium is installed")
        return 1


if __name__ == "__main__":
    exit(main())

