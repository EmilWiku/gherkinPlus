#!/usr/bin/env python3
"""Simple test to see login page structure"""
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time

try:
    from webdriver_manager.chrome import ChromeDriverManager
    service = Service(ChromeDriverManager().install())
except:
    service = None

chrome_options = Options()
# Don't run headless so we can see what's happening
chrome_options.add_argument('--start-maximized')
chrome_options.add_experimental_option("detach", True)  # Keep browser open

if service:
    driver = webdriver.Chrome(service=service, options=chrome_options)
else:
    driver = webdriver.Chrome(options=chrome_options)

print("🌐 Opening PocketOption...")
driver.get("https://pocketoption.com/login")
time.sleep(5)

print("\n📋 Page Analysis:")
print(f"Title: {driver.title}")
print(f"URL: {driver.current_url}")

# Find all input fields
print("\n🔍 Input fields found:")
inputs = driver.find_elements(By.TAG_NAME, "input")
for i, inp in enumerate(inputs):
    inp_type = inp.get_attribute("type") or "text"
    inp_name = inp.get_attribute("name") or ""
    inp_id = inp.get_attribute("id") or ""
    inp_placeholder = inp.get_attribute("placeholder") or ""
    inp_class = inp.get_attribute("class") or ""
    is_displayed = inp.is_displayed()
    print(f"  {i+1}. Type: {inp_type}, Name: {inp_name}, ID: {inp_id}")
    print(f"     Placeholder: {inp_placeholder}, Class: {inp_class[:50]}")
    print(f"     Displayed: {is_displayed}")

# Find all buttons
print("\n🔍 Buttons found:")
buttons = driver.find_elements(By.TAG_NAME, "button")
for i, btn in enumerate(buttons):
    btn_text = btn.text or ""
    btn_type = btn.get_attribute("type") or ""
    btn_class = btn.get_attribute("class") or ""
    is_displayed = btn.is_displayed()
    print(f"  {i+1}. Text: '{btn_text}', Type: {btn_type}")
    print(f"     Class: {btn_class[:50]}, Displayed: {is_displayed}")

print("\n⏸️ Browser will stay open for 30 seconds for manual inspection...")
print("   You can manually fill the form to see what works")
time.sleep(30)

driver.quit()

