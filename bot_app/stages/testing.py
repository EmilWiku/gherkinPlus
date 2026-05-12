"""
Testing Stage - Interface and implementations for connection testing
"""
from abc import ABC, abstractmethod
from typing import Optional
from pocketoptionapi_async import AsyncPocketOptionClient
import asyncio


class TestingStage(ABC):
    """Abstract interface for testing stage"""
    
    @abstractmethod
    async def test_connection(self, ssid: str, is_demo: bool = False, proxy_url: Optional[str] = None) -> bool:
        """
        Test connection to PocketOption.
        
        Args:
            ssid: Session ID string
            is_demo: Whether to use demo account
            proxy_url: Optional proxy URL for connection
        
        Returns:
            True if connection successful, False otherwise
        """
        pass


class DefaultTestingStage(TestingStage):
    """Default implementation of testing stage"""
    
    async def test_connection(self, ssid: str, is_demo: bool = False, proxy_url: Optional[str] = None) -> bool:
        """Test connection to PocketOption"""
        print("=" * 60)
        print("🔍 Testing Connection...")
        if proxy_url:
            masked = proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url
            print(f"🌐 Using proxy: {masked}")
        print("=" * 60)
        
        client = None
        try:
            client = AsyncPocketOptionClient(ssid, is_demo=is_demo, enable_logging=False, proxy_url=proxy_url)
            await client.connect()
            
            if not client.is_connected:
                print("❌ Connection failed")
                return False
            
            print("✅ Connection established!")
            await asyncio.sleep(2)
            
            candles_df = await client.get_candles_dataframe(asset='EURUSD_otc', timeframe=60)
            
            if candles_df is not None and not candles_df.empty:
                print(f"✅ Data retrieval successful! ({len(candles_df)} candles)")
                print("=" * 60)
                print("✅ Connection test PASSED!")
                print("=" * 60)
                return True
            else:
                print("⚠️ No candle data received")
                return False
                
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
        
        return False

