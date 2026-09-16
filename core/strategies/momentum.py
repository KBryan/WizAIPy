"""
Momentum trading strategy implementation.
Follows price trends and momentum indicators.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import numpy as np

from .base import (
    BaseStrategy, TradingSignal, MarketData, PortfolioPosition,
    SignalType, StrategyConfig
)


class MomentumStrategy(BaseStrategy):
    """
    Momentum trading strategy that follows price trends.
    
    This strategy analyzes price momentum using moving averages and
    generates buy/sell signals based on trend direction and strength.
    """
    
    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        
        # Strategy parameters
        self.lookback_period = config.parameters.get("lookback_period", 14)
        self.momentum_threshold = config.parameters.get("momentum_threshold", 0.05)
        self.volume_threshold = config.parameters.get("volume_threshold", 1000000)
        self.short_ma_period = config.parameters.get("short_ma_period", 5)
        self.long_ma_period = config.parameters.get("long_ma_period", 20)
        
        # Internal state
        self.price_history: Dict[str, List[float]] = {}
        self.volume_history: Dict[str, List[float]] = {}
        self.last_signals: Dict[str, TradingSignal] = {}
    
    async def analyze_market(self, market_data: List[MarketData]) -> Optional[TradingSignal]:
        """
        Analyze market data for momentum signals.
        
        Args:
            market_data: List of market data points
            
        Returns:
            TradingSignal if momentum detected, None otherwise
        """
        try:
            # Update price and volume history
            self._update_history(market_data)
            
            # Analyze each token for momentum
            for data in market_data:
                signal = await self._analyze_token_momentum(data)
                if signal:
                    return signal
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error in momentum analysis: {e}")
            return None
    
    async def _analyze_token_momentum(self, data: MarketData) -> Optional[TradingSignal]:
        """
        Analyze momentum for a specific token.
        
        Args:
            data: Market data for the token
            
        Returns:
            TradingSignal if momentum detected, None otherwise
        """
        symbol = data.symbol
        
        # Need sufficient history for analysis
        if (symbol not in self.price_history or 
            len(self.price_history[symbol]) < self.long_ma_period):
            return None
        
        prices = self.price_history[symbol]
        # _update_history has already appended the current bar; compare the current
        # volume against the history *before* it, not against an average of itself.
        volumes = self.volume_history.get(symbol, [])[:-1]
        
        # Calculate momentum indicators
        momentum_score = self._calculate_momentum_score(prices)
        ma_signal = self._calculate_ma_crossover(prices)
        volume_confirmation = self._check_volume_confirmation(volumes, data.volume_24h)
        
        # Generate signal based on momentum analysis
        signal_type = self._determine_signal_type(momentum_score, ma_signal, volume_confirmation)
        
        if signal_type == SignalType.HOLD:
            return None
        
        # Calculate confidence based on multiple factors
        confidence = self._calculate_confidence(momentum_score, ma_signal, volume_confirmation)
        
        # Determine trade amount based on confidence and momentum strength
        amount = self._calculate_trade_amount(confidence, momentum_score)
        
        signal = TradingSignal(
            signal_type=signal_type,
            token_in="ETH" if signal_type == SignalType.BUY else symbol,
            token_out=symbol if signal_type == SignalType.BUY else "ETH",
            amount=amount,
            confidence=confidence,
            timestamp=datetime.utcnow(),
            metadata={
                "momentum_score": momentum_score,
                "ma_signal": ma_signal,
                "volume_confirmation": volume_confirmation,
                "price": data.price,
                "volume_24h": data.volume_24h
            },
            strategy_id=self.config.strategy_id,
            reason=f"Momentum {signal_type.value} signal: score={momentum_score:.3f}, confidence={confidence:.3f}"
        )
        
        # Store last signal for this token
        self.last_signals[symbol] = signal
        
        return signal
    
    def _calculate_momentum_score(self, prices: List[float]) -> float:
        """
        Calculate momentum score based on price changes.
        
        Args:
            prices: Historical prices
            
        Returns:
            Momentum score (-1 to 1)
        """
        if len(prices) < self.lookback_period:
            return 0.0
        
        # Calculate rate of change over lookback period
        current_price = prices[-1]
        past_price = prices[-self.lookback_period]
        
        if past_price == 0:
            return 0.0
        
        rate_of_change = (current_price - past_price) / past_price
        
        # Normalize to -1 to 1 range
        momentum_score = np.tanh(rate_of_change * 10)  # Scale factor for sensitivity
        
        return momentum_score
    
    def _calculate_ma_crossover(self, prices: List[float]) -> int:
        """
        Calculate moving average alignment signal.
        
        Reports whether the short MA currently sits above or below the long MA,
        i.e. the state left behind by the most recent crossover. This is used as
        a trend filter by _determine_signal_type, so it must stay set for as long
        as the alignment holds rather than firing only on the bar of the cross.
        
        Args:
            prices: Historical prices
            
        Returns:
            1 if short MA is above long MA (bullish), -1 if below (bearish),
            0 if equal or insufficient history
        """
        if len(prices) < self.long_ma_period:
            return 0
        
        short_ma = np.mean(prices[-self.short_ma_period:])
        long_ma = np.mean(prices[-self.long_ma_period:])
        
        if short_ma > long_ma:
            return 1  # Bullish alignment
        elif short_ma < long_ma:
            return -1  # Bearish alignment
        
        return 0
    
    def _check_volume_confirmation(self, volumes: List[float], current_volume: float) -> bool:
        """
        Check if volume confirms the momentum signal.
        
        Args:
            volumes: Historical volumes
            current_volume: Current 24h volume
            
        Returns:
            True if volume confirms momentum, False otherwise
        """
        if not volumes or current_volume < self.volume_threshold:
            return False
        
        # Check if current volume is at least 20% above average
        avg_volume = np.mean(volumes[-self.lookback_period:]) if len(volumes) >= self.lookback_period else np.mean(volumes)
        
        return bool(current_volume >= avg_volume * 1.2)  # np.bool_ -> bool
    
    def _determine_signal_type(self, momentum_score: float, ma_signal: int, volume_confirmation: bool) -> SignalType:
        """
        Determine signal type based on momentum indicators.
        
        Args:
            momentum_score: Momentum score (-1 to 1)
            ma_signal: MA crossover signal (-1, 0, 1)
            volume_confirmation: Volume confirmation
            
        Returns:
            Signal type
        """
        # Strong bullish momentum
        if (momentum_score > self.momentum_threshold and 
            ma_signal >= 0 and 
            volume_confirmation):
            return SignalType.BUY
        
        # Strong bearish momentum
        if (momentum_score < -self.momentum_threshold and 
            ma_signal <= 0 and 
            volume_confirmation):
            return SignalType.SELL
        
        return SignalType.HOLD
    
    def _calculate_confidence(self, momentum_score: float, ma_signal: int, volume_confirmation: bool) -> float:
        """
        Calculate confidence score for the signal.
        
        Args:
            momentum_score: Momentum score
            ma_signal: MA crossover signal
            volume_confirmation: Volume confirmation
            
        Returns:
            Confidence score (0 to 1)
        """
        confidence = 0.0
        
        # Base confidence from momentum strength
        confidence += min(abs(momentum_score), 1.0) * 0.4
        
        # MA crossover confirmation
        if ma_signal != 0:
            confidence += 0.3
        
        # Volume confirmation
        if volume_confirmation:
            confidence += 0.3
        
        return min(confidence, 1.0)
    
    def _calculate_trade_amount(self, confidence: float, momentum_score: float) -> float:
        """
        Calculate trade amount based on confidence and momentum.
        
        Args:
            confidence: Signal confidence
            momentum_score: Momentum score
            
        Returns:
            Trade amount
        """
        # Base amount from configuration
        base_amount = self.config.parameters.get("base_trade_amount", 0.1)
        
        # Scale by confidence and momentum strength
        amount = base_amount * confidence * min(abs(momentum_score) * 2, 1.0)
        
        return max(amount, 0.01)  # Minimum trade amount
    
    def _update_history(self, market_data: List[MarketData]):
        """
        Update price and volume history with new market data.
        
        Args:
            market_data: New market data points
        """
        max_history = max(self.long_ma_period * 2, 50)  # Keep enough history
        
        for data in market_data:
            symbol = data.symbol
            
            # Initialize history if needed
            if symbol not in self.price_history:
                self.price_history[symbol] = []
                self.volume_history[symbol] = []
            
            # Add new data
            self.price_history[symbol].append(data.price)
            self.volume_history[symbol].append(data.volume_24h)
            
            # Trim history to max length
            if len(self.price_history[symbol]) > max_history:
                self.price_history[symbol] = self.price_history[symbol][-max_history:]
                self.volume_history[symbol] = self.volume_history[symbol][-max_history:]
    
    async def validate_signal(self, signal: TradingSignal, portfolio: List[PortfolioPosition]) -> bool:
        """
        Validate momentum signal against portfolio and risk limits.
        
        Args:
            signal: Trading signal to validate
            portfolio: Current portfolio positions
            
        Returns:
            True if signal is valid, False otherwise
        """
        # Check base risk limits
        if not self.check_risk_limits(signal, portfolio):
            return False
        
        # Check for recent signals on same token to avoid overtrading
        token = signal.token_out if signal.signal_type == SignalType.BUY else signal.token_in
        
        if token in self.last_signals:
            last_signal = self.last_signals[token]
            time_since_last = (signal.timestamp - last_signal.timestamp).total_seconds()
            min_interval = self.config.parameters.get("min_signal_interval", 3600)  # 1 hour
            
            if time_since_last < min_interval:
                self.logger.info(f"Signal too soon after last signal for {token}: {time_since_last}s < {min_interval}s")
                return False
        
        # Check momentum strength threshold
        momentum_score = signal.metadata.get("momentum_score", 0)
        if abs(momentum_score) < self.momentum_threshold:
            self.logger.info(f"Momentum too weak: {abs(momentum_score)} < {self.momentum_threshold}")
            return False
        
        return True
    
    def get_required_data(self) -> List[str]:
        """
        Get list of required market data symbols.
        
        Returns:
            List of token symbols to monitor
        """
        # Default tokens to monitor for momentum
        return self.config.parameters.get("monitored_tokens", [
            "ETH", "BTC", "USDC", "USDT", "BNB", "ADA", "SOL", "DOT", "MATIC", "LINK"
        ])

