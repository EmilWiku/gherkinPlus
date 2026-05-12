"""
Evaluation Stage - Interface and implementations for opportunity evaluation
"""
import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from pocketoptionapi_async.models import Candle


class EvaluationStage(ABC):
    """Abstract interface for evaluation stage"""
    
    @abstractmethod
    async def analyze_asset(self, asset: str, client, db, asset_inner_confidence: Dict) -> Dict:
        """
        Analyze a single asset.
        
        Args:
            asset: Asset symbol
            client: PocketOption client
            db: Database instance
            asset_inner_confidence: Dict to store/cache inner confidence
        
        Returns:
            Analysis dict with confidence score and signal
        """
        pass
    
    @abstractmethod
    async def find_opportunities(self, assets: List[str], client, db, 
                                 assets_by_category: Optional[Dict] = None,
                                 asset_inner_confidence: Dict = None,
                                 asset_payout_percentages: Dict = None,
                                 asset_performance: Dict = None) -> List[Dict]:
        """
        Find and filter trading opportunities.
        
        Args:
            assets: List of asset symbols to analyze
            client: PocketOption client
            db: Database instance
            assets_by_category: Optional dict mapping categories to assets
            asset_inner_confidence: Dict for inner confidence cache
            asset_payout_percentages: Dict for payout percentages
            asset_performance: Dict for asset performance data
        
        Returns:
            List of validated opportunities
        """
        pass


class DefaultEvaluationStage(EvaluationStage):
    """Default implementation of evaluation stage"""
    
    def __init__(self, confidence_scorer, technical_analyzer, risk_manager, config):
        """
        Initialize with required components.
        
        Args:
            confidence_scorer: ConfidenceScorer instance
            technical_analyzer: TechnicalAnalyzer instance
            risk_manager: RiskManager instance
            config: TradingConfig instance
        """
        self.confidence_scorer = confidence_scorer
        self.technical_analyzer = technical_analyzer
        self.risk_manager = risk_manager
        self.config = config
    
    async def get_asset_inner_confidence(self, asset: str, client, asset_inner_confidence: Dict) -> Optional[float]:
        """Get inner confidence for OTC assets"""
        try:
            if asset in asset_inner_confidence:
                return asset_inner_confidence[asset]
            
            if "_otc" in asset.lower():
                message1 = f'42["getAssetInfo",{{"asset":"{asset}"}}]'
                message2 = f'42["getOTCConfidence",{{"asset":"{asset}"}}]'
                await client.send_message(message1)
                await client.send_message(message2)
                await asyncio.sleep(0.8)
                
                if asset in asset_inner_confidence:
                    return asset_inner_confidence[asset]
            
            return None
        except Exception:
            return None
    
    async def analyze_asset(self, asset: str, client, db, asset_inner_confidence: Dict) -> Dict:
        """Analyze a single asset with multi-timeframe analysis"""
        try:
            # Get inner confidence for OTC assets
            inner_confidence = None
            if "_otc" in asset.lower():
                inner_confidence = await self.get_asset_inner_confidence(asset, client, asset_inner_confidence)
            
            # Get candle data
            candles_1m = await client.get_candles(asset=asset, timeframe=60, count=100)
            candles_5m = await client.get_candles(asset=asset, timeframe=300, count=50)
            
            if not candles_1m or len(candles_1m) < 30:
                return {"error": "Insufficient data", "asset": asset}
            
            # Get historical stats
            asset_stats = db.get_asset_stats(asset)
            
            # Calculate confidence
            analysis = self.confidence_scorer.calculate_confidence(candles_1m, candles_5m, asset_stats)
            analysis["asset"] = asset
            analysis["inner_confidence"] = inner_confidence
            
            return analysis
        except Exception as e:
            return {"error": str(e), "asset": asset}
    
    async def find_opportunities(self, assets: List[str], client, db, 
                                 assets_by_category: Optional[Dict] = None,
                                 asset_inner_confidence: Dict = None,
                                 asset_payout_percentages: Dict = None,
                                 asset_performance: Dict = None) -> List[Dict]:
        """Find and filter trading opportunities"""
        
        if asset_inner_confidence is None:
            asset_inner_confidence = {}
        if asset_payout_percentages is None:
            asset_payout_percentages = {}
        if asset_performance is None:
            asset_performance = {}
        
        print(f"📊 Analyzing {len(assets)} assets...")
        
        # Analyze all assets in parallel
        tasks = [self.analyze_asset(asset, client, db, asset_inner_confidence) for asset in assets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Initial filtering
        candidates = []
        rejected_count = 0
        rejection_reasons = {}
        
        for result in results:
            if isinstance(result, Exception) or "error" in result:
                rejected_count += 1
                continue
            
            asset = result.get("asset", "")
            confidence = result.get("confidence_score", 0)
            direction = result.get("signal_direction")
            inner_confidence = result.get("inner_confidence")
            
            # OTC inner confidence check
            if "_otc" in asset.lower():
                if inner_confidence is not None and inner_confidence < self.config.MIN_OTC_INNER_CONFIDENCE:
                    rejected_count += 1
                    reason = f"Inner confidence {inner_confidence:.1f}% < {self.config.MIN_OTC_INNER_CONFIDENCE}%"
                    rejection_reasons[asset] = reason
                    continue
                elif inner_confidence is None:
                    inner_confidence = await self.get_asset_inner_confidence(asset, client, asset_inner_confidence)
                    if inner_confidence is not None and inner_confidence < self.config.MIN_OTC_INNER_CONFIDENCE:
                        rejected_count += 1
                        reason = f"Inner confidence {inner_confidence:.1f}% < {self.config.MIN_OTC_INNER_CONFIDENCE}%"
                        rejection_reasons[asset] = reason
                        continue
            
            # Store payout if available
            payout = asset_payout_percentages.get(asset)
            if payout:
                result["payout_percentage"] = payout
            
            # Check basic requirements
            if not direction:
                rejected_count += 1
                rejection_reasons[asset] = "No signal direction"
                continue
            
            if confidence < self.config.MIN_CONFIDENCE:
                rejected_count += 1
                rejection_reasons[asset] = f"Confidence {confidence:.1f}% < {self.config.MIN_CONFIDENCE}%"
                continue
            
            candidates.append(result)
        
        # Log rejection summary
        if rejected_count > 0:
            print(f"📊 Analysis complete: {len(candidates)} candidates, {rejected_count} rejected")
        
        if not candidates:
            print(f"⚠️ No assets meet confidence threshold ({self.config.MIN_CONFIDENCE}%+)")
            return []
        
        # Sort by confidence
        candidates.sort(key=lambda x: x.get("confidence_score", 0), reverse=True)
        
        # Apply filters
        validated = []
        categories_used = set()
        filter_rejections = {}
        
        print(f"\n🔍 Validating {len(candidates)} candidates...")
        
        for opp in candidates:
            asset = opp.get("asset", "")
            asset_stats = db.get_asset_stats(asset)
            
            # Validate entry criteria
            is_valid, reason = self.risk_manager.validate_entry_opportunity(
                opp, asset_stats, categories_used, assets_by_category, asset_performance
            )
            
            if not is_valid:
                filter_rejections[asset] = reason
                continue
            
            validated.append(opp)
            if assets_by_category:
                category = self.risk_manager._get_asset_category(asset, assets_by_category)
                categories_used.add(category)
            
            # Log successful validation
            confidence = opp.get("confidence_score", 0)
            direction = opp.get("signal_direction", "")
            factors_count = len(opp.get("confidence_factors", []))
            print(f"   ✅ {asset}: {direction} - {confidence:.1f}% confidence ({factors_count} factors)")
            
            # Limit positions per cycle
            if len(validated) >= self.config.MAX_POSITIONS_PER_CYCLE:
                print(f"   ⏸️  Reached max positions per cycle ({self.config.MAX_POSITIONS_PER_CYCLE})")
                break
        
        return validated

