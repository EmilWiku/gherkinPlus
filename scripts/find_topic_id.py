"""
Find Telegram forum topic / thread ID for a supergroup with topics.

Usage:
  1. Add the bot as admin to the group.
  2. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID in `.env`.
  3. Run: python scripts/find_topic_id.py
  4. Send a message in the target topic; the script prints message_thread_id.
"""
import asyncio
import aiohttp
import ssl
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "bot_app"))

from env_setup import load_dotenv_early, require_env

load_dotenv_early()

BOT_TOKEN = require_env("TELEGRAM_BOT_TOKEN")
GROUP_ID = require_env("TELEGRAM_CHANNEL_ID").lstrip("@")

async def find_topic_id():
    """Find topic ID by monitoring Telegram updates"""
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
    
    # Create SSL context
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    
    print("🔍 Looking for topic ID...")
    print(f"📱 Group ID: {GROUP_ID}\n")
    
    last_update_id = 0
    
    async with aiohttp.ClientSession(connector=connector) as session:
        # Try to get forum topics directly (if API supports it)
        try:
            url = f"{base_url}/getForumTopics"
            payload = {"chat_id": GROUP_ID if GROUP_ID.startswith("-") else f"@{GROUP_ID}"}
            
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("ok") and data.get("result"):
                        topics = data["result"].get("topics", [])
                        if topics:
                            print("📋 Found topics:")
                            for topic in topics:
                                topic_id = topic.get("message_thread_id")
                                topic_name = topic.get("name", "Unknown")
                                print(f"   • {topic_name}: ID = {topic_id}")
                                
                                if "VIP" in topic_name or "сессии" in topic_name.lower():
                                    print(f"\n✅ Found 'VIP сессии' topic!")
                                    print(f"💡 Set TELEGRAM_TOPIC_ID={topic_id} in .env")
                                    return topic_id
                            
                            print("\n💡 If 'VIP сессии' is listed above, use its ID")
                            print("   Otherwise, continue with the monitoring method below...\n")
        except Exception as e:
            print(f"⚠️  Could not get topics list (API might not support it): {e}\n")
            print("📝 Using alternative method: monitoring messages...\n")
        
        print("📝 Please send a message to the 'VIP сессии' topic in the group now...")
        print("⏳ Waiting for messages...\n")
        while True:
            try:
                # Get updates
                url = f"{base_url}/getUpdates"
                params = {"offset": last_update_id + 1, "timeout": 10}
                
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if data.get("ok") and data.get("result"):
                            for update in data["result"]:
                                last_update_id = update["update_id"]
                                
                                # Check if this is a message update
                                if "message" in update:
                                    message = update["message"]
                                    chat = message.get("chat", {})
                                    message_thread_id = message.get("message_thread_id")
                                    
                                    # Check if message is from our group
                                    chat_id = str(chat.get("id", ""))
                                    if chat_id == GROUP_ID or (GROUP_ID.isdigit() and chat_id == GROUP_ID):
                                        if message_thread_id:
                                            print(f"✅ Found topic ID: {message_thread_id}")
                                            print(f"📋 Topic name: {message.get('text', 'N/A')[:50]}")
                                            print(f"\n💡 Set TELEGRAM_TOPIC_ID={message_thread_id} in .env")
                                            return message_thread_id
                                        else:
                                            print("⚠️  Message received but no topic ID (message not in a topic)")
                                
                                # Check if this is a channel post update
                                if "channel_post" in update:
                                    channel_post = update["channel_post"]
                                    message_thread_id = channel_post.get("message_thread_id")
                                    
                                    if message_thread_id:
                                        print(f"✅ Found topic ID: {message_thread_id}")
                                        print(f"📋 Topic name: {channel_post.get('text', 'N/A')[:50]}")
                                        print(f"\n💡 Set TELEGRAM_TOPIC_ID={message_thread_id} in .env")
                                        return message_thread_id
                
                await asyncio.sleep(1)
                
            except KeyboardInterrupt:
                print("\n\n⚠️  Interrupted by user")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(find_topic_id())
    except KeyboardInterrupt:
        print("\n\n👋 Exiting...")

