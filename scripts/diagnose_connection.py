#!/usr/bin/env python3
"""Diagnose connection issues and optionally get SSID automatically"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "bot_app"))
sys.path.insert(0, str(_REPO / "PocketOptionAPI"))

from env_setup import get_pocket_option_ssid, load_dotenv_early
from pocketoptionapi_async import AsyncPocketOptionClient
from datetime import datetime

load_dotenv_early()


async def test_connection(ssid: str = None):
    """Test connection with provided SSID, ssid.txt, or environment."""

    if not ssid:
        for candidate in (_REPO / "ssid.txt", _REPO / "data" / "ssid.txt"):
            if candidate.is_file():
                ssid = candidate.read_text(encoding="utf-8").strip()
                break
    if not ssid:
        ssid = get_pocket_option_ssid()
    
    print("🔍 Connection Diagnostics")
    print("=" * 60)
    
    # Parse SSID
    import json
    import re
    
    try:
        if ssid.startswith('42["auth",'):
            json_start = ssid.find("{")
            json_end = ssid.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_part = ssid[json_start:json_end]
                data = json.loads(json_part)
                session_value = data.get("session", "")
                is_demo = bool(data.get("isDemo", 0))
                uid = data.get("uid", 0)
                
                # Extract session_id
                if "session_id" in session_value:
                    session_id_match = re.search(r'session_id";s:\d+:"([^"]+)"', session_value)
                    if session_id_match:
                        session_id = session_id_match.group(1)
                    else:
                        session_id = session_value
                else:
                    session_id = session_value
                
                print(f"✅ SSID parsed successfully")
                print(f"   Session ID: {session_id[:20]}...")
                print(f"   UID: {uid}")
                print(f"   Demo: {is_demo}")
                
                # Check last_activity
                if "last_activity" in session_value:
                    last_activity_match = re.search(r'last_activity";i:(\d+)', session_value)
                    if last_activity_match:
                        last_activity = int(last_activity_match.group(1))
                        last_activity_dt = datetime.fromtimestamp(last_activity)
                        age_days = (datetime.now() - last_activity_dt).days
                        print(f"   Last Activity: {last_activity_dt} ({age_days} days ago)")
                        if age_days > 1:
                            print(f"   ⚠️ WARNING: SSID is {age_days} days old - may be expired!")
    except Exception as e:
        print(f"❌ Error parsing SSID: {e}")
        return
    
    # Test network connectivity
    print("\n🌐 Testing network connectivity...")
    try:
        import socket
        # Test DNS
        socket.gethostbyname("pocketoption.com")
        print("   ✅ DNS resolution OK")
        
        # Test HTTPS connection
        import ssl
        context = ssl.create_default_context()
        with socket.create_connection(("pocketoption.com", 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname="pocketoption.com"):
                print("   ✅ HTTPS connection OK")
    except Exception as e:
        print(f"   ❌ Network issue: {e}")
        print("   ⚠️ Server may not have internet access or firewall is blocking")
        return
    
    # Test WebSocket connection
    print("\n🔌 Testing WebSocket connection...")
    client = AsyncPocketOptionClient(ssid, is_demo=is_demo, enable_logging=True)
    
    try:
        print("   Attempting connection...")
        success = await asyncio.wait_for(client.connect(), timeout=30)
        
        if success:
            print("   ✅ Connection successful!")
            
            # Try to get balance
            try:
                balance = await client.get_balance()
                if balance:
                    print(f"   ✅ Balance retrieved: ${balance.balance}")
                else:
                    print("   ⚠️ No balance data (SSID may be invalid)")
            except Exception as e:
                print(f"   ⚠️ Balance request failed: {e}")
            
            await client.disconnect()
        else:
            print("   ❌ Connection failed")
            print("   Possible reasons:")
            print("     1. SSID expired (get new one from browser)")
            print("     2. Account blocked or restricted")
            print("     3. Server IP blocked by PocketOption")
            
    except asyncio.TimeoutError:
        print("   ❌ Connection timeout")
        print("   Possible reasons:")
        print("     1. Firewall blocking WebSocket connections")
        print("     2. Network issues")
        print("     3. PocketOption servers unreachable")
    except Exception as e:
        print(f"   ❌ Connection error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("💡 Recommendations:")
    print("   1. Get a fresh SSID: python3 get_ssid_automated.py")
    print("   2. Check if server has internet access: curl https://pocketoption.com")
    print("   3. Check firewall rules: iptables -L")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--ssid', help='SSID to test (or use ssid.txt file)')
    args = parser.parse_args()
    
    asyncio.run(test_connection(args.ssid))
