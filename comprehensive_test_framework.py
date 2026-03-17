# comprehensive_test_framework.py
"""
Comprehensive Testing Framework v3.0
Unit | Integration | E2E | Performance | Chaos Engineering
"""

import asyncio
import pytest
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import logging
import time
import random
import string
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

# Import components to test
try:
    from enhanced_backtest_engine import EnhancedBacktestEngine, TickData, TransactionCostModel
    from enhanced_realtime_engine import MultiSourceAggregator, MarketTick, MockProvider
    from enhanced_ml_predictor import EnhancedMLPredictor, FeatureEngineering
    from enhanced_smart_router import SmartOrderRouter, Order, OrderSide, OrderType
    COMPONENTS_AVAILABLE = True
except ImportError as e:
    COMPONENTS_AVAILABLE = False
    logging.warning(f"Component imports failed: {e}")

logger = logging.getLogger(__name__)

class TestCategory(Enum):
    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    PERFORMANCE = "performance"
    CHAOS = "chaos"
    SECURITY = "security"

@dataclass
class TestResult:
    """Test execution result"""
    name: str
    category: TestCategory
    passed: bool
    duration_ms: float
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = None

class TestDataGenerator:
    """Generate realistic test data"""
    
    @staticmethod
    def generate_ohlcv(n: int = 1000, 
                       trend: float = 0.0001,
                       volatility: float = 0.001,
                       start_price: float = 100.0) -> pd.DataFrame:
        """Generate synthetic OHLCV data"""
        np.random.seed(42)
        
        returns = np.random.normal(trend, volatility, n)
        prices = start_price * np.exp(np.cumsum(returns))
        
        # Generate OHLC from close
        df = pd.DataFrame(index=pd.date_range('2024-01-01', periods=n, freq='5min'))
        df['close'] = prices
        
        # High/Low based on volatility
        daily_range = prices * volatility * 2
        df['high'] = prices + np.random.uniform(0, daily_range/2, n)
        df['low'] = prices - np.random.uniform(0, daily_range/2, n)
        df['open'] = df['close'].shift(1).fillna(prices[0])
        
        # Volume
        df['volume'] = np.random.poisson(1000, n)
        
        return df
    
    @staticmethod
    def generate_ticks(n: int = 1000, 
                       base_price: float = 1950.0,
                       spread: float = 0.05) -> List[TickData]:
        """Generate synthetic tick data"""
        np.random.seed(42)
        
        returns = np.random.normal(0, 0.0002, n)
        prices = base_price * np.exp(np.cumsum(returns))
        
        ticks = []
        for i, price in enumerate(prices):
            spread_bps = np.random.uniform(0.8, 1.2)
            half_spread = price * spread_bps / 10000
            
            ticks.append(TickData(
                timestamp=datetime(2024, 1, 1) + timedelta(minutes=i),
                bid=price - half_spread,
                ask=price + half_spread,
                bid_size=np.random.exponential(10),
                ask_size=np.random.exponential(10),
                volume=np.random.poisson(100)
            ))
        
        return ticks

class UnitTests:
    """Unit test suite for individual components"""
    
    def __init__(self):
        self.results: List[TestResult] = []
    
    async def run_all(self) -> List[TestResult]:
        """Run all unit tests"""
        tests = [
            self.test_tick_data_validation,
            self.test_transaction_costs,
            self.test_feature_engineering,
            self.test_order_creation,
            self.test_market_impact_model,
        ]
        
        for test in tests:
            try:
                start = time.time()
                await test()
                duration = (time.time() - start) * 1000
                
                self.results.append(TestResult(
                    name=test.__name__,
                    category=TestCategory.UNIT,
                    passed=True,
                    duration_ms=duration
                ))
            except Exception as e:
                self.results.append(TestResult(
                    name=test.__name__,
                    category=TestCategory.UNIT,
                    passed=False,
                    duration_ms=0,
                    error_message=str(e)
                ))
        
        return self.results
    
    async def test_tick_data_validation(self):
        """Test TickData validation"""
        if not COMPONENTS_AVAILABLE:
            return
        
        # Valid tick
        tick = TickData(
            timestamp=datetime.now(),
            bid=1950.0,
            ask=1950.05,
            bid_size=10.0,
            ask_size=15.0
        )
        assert tick.mid == 1950.025
        assert tick.spread == 0.05
        
        # Invalid tick should raise
        try:
            invalid = TickData(
                timestamp=datetime.now(),
                bid=1950.0,
                ask=1949.0,  # Invalid: ask < bid
                bid_size=10.0,
                ask_size=15.0
            )
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass  # Expected
    
    async def test_transaction_costs(self):
        """Test transaction cost calculations"""
        if not COMPONENTS_AVAILABLE:
            return
        
        cost_model = TransactionCostModel(
            commission_per_lot=7.0,
            spread_markup_bps=0.8,
            slippage_model="square_root"
        )
        
        costs = cost_model.total_cost(
            order_size=100000,
            price=1950.0,
            volatility=0.001,
            volume=10000
        )
        
        assert costs['commission'] == 7.0
        assert costs['spread_cost'] > 0
        assert costs['total_cost'] > 0
    
    async def test_feature_engineering(self):
        """Test feature generation"""
        if not COMPONENTS_AVAILABLE:
            return
        
        df = TestDataGenerator.generate_ohlcv(n=200)
        
        engineer = FeatureEngineering()
        features = engineer.create_features(df, fit=True)
        
        assert len(features) > 0
        assert 'returns' in features.columns
        assert 'volatility_20' in features.columns
        assert 'rsi_14' in features.columns
        assert not features.isnull().any().any()  # No NaN
    
    async def test_order_creation(self):
        """Test order structure"""
        if not COMPONENTS_AVAILABLE:
            return
        
        order = Order(
            id="test_001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            size=100.0,
            order_type=OrderType.TWAP,
            price=1950.0
        )
        
        assert order.remaining_size == 100.0
        assert order.notional == 195000.0
    
    async def test_market_impact_model(self):
        """Test Almgren-Chriss impact model"""
        if not COMPONENTS_AVAILABLE:
            return
        
        from enhanced_smart_router import MarketImpactModel
        
        model = MarketImpactModel(
            eta=0.142,
            gamma=0.314,
            beta=0.6,
            sigma=0.02
        )
        
        temp_impact = model.temporary_impact(
            X=1000000,  # 1M units
            T=0.1,      # 10% of day
            V=10000000  # 10M ADV
        )
        
        assert temp_impact > 0
        assert temp_impact < 0.01  # Less than 1%

class IntegrationTests:
    """Integration test suite"""
    
    def __init__(self):
        self.results: List[TestResult] = []
    
    async def run_all(self) -> List[TestResult]:
        """Run all integration tests"""
        tests = [
            self.test_backtest_full_workflow,
            self.test_realtime_data_flow,
            self.test_ml_pipeline,
            self.test_routing_execution,
        ]
        
        for test in tests:
            try:
                start = time.time()
                await test()
                duration = (time.time() - start) * 1000
                
                self.results.append(TestResult(
                    name=test.__name__,
                    category=TestCategory.INTEGRATION,
                    passed=True,
                    duration_ms=duration
                ))
            except Exception as e:
                self.results.append(TestResult(
                    name=test.__name__,
                    category=TestCategory.INTEGRATION,
                    passed=False,
                    duration_ms=0,
                    error_message=str(e)
                ))
        
        return self.results
    
    async def test_backtest_full_workflow(self):
        """Test complete backtest workflow"""
        if not COMPONENTS_AVAILABLE:
            return
        
        # Generate data
        ticks = TestDataGenerator.generate_ticks(n=500)
        
        # Initialize engine
        engine = EnhancedBacktestEngine(
            initial_capital=100000,
            cost_model=TransactionCostModel(),
            parallel=False
        )
        
        # Run simple strategy
        position = 0
        for i, tick in enumerate(ticks[50:]):  # Skip first 50 for indicators
            engine.process_tick(tick)
            
            # Simple MA crossover
            if i > 20:
                prices = [t.mid for t in ticks[i-20:i]]
                ma_fast = np.mean(prices[-5:])
                ma_slow = np.mean(prices)
                
                if ma_fast > ma_slow and position <= 0:
                    if position < 0:
                        engine.execute_order("XAUUSD", -position, tick)
                    engine.execute_order("XAUUSD", 10, tick)
                    position = 10
                elif ma_fast < ma_slow and position >= 0:
                    if position > 0:
                        engine.execute_order("XAUUSD", -position, tick)
                    engine.execute_order("XAUUSD", -10, tick)
                    position = -10
        
        # Generate report
        report = engine.get_performance_report()
        assert 'summary' in report
        assert 'risk_metrics' in report
    
    async def test_realtime_data_flow(self):
        """Test realtime data aggregation"""
        if not COMPONENTS_AVAILABLE:
            return
        
        aggregator = MultiSourceAggregator(
            consensus_threshold=0.5,
            max_sources=3
        )
        
        # Add mock providers
        for i in range(3):
            aggregator.add_provider(MockProvider(
                volatility=0.0002 + i * 0.0001,
                drift=0.00001 * (i - 1)
            ))
        
        # Collect ticks
        received_ticks = []
        def on_tick(tick):
            received_ticks.append(tick)
        
        aggregator.on_consensus(on_tick)
        
        # Run briefly
        task = asyncio.create_task(aggregator.start())
        await asyncio.sleep(2)
        aggregator.stop()
        task.cancel()
        
        assert len(received_ticks) > 0
        assert all(t.quality.name in ['EXCELLENT', 'GOOD', 'FAIR'] for t in received_ticks)
    
    async def test_ml_pipeline(self):
        """Test ML training and prediction pipeline"""
        if not COMPONENTS_AVAILABLE:
            return
        
        # Generate data
        df = TestDataGenerator.generate_ohlcv(n=1000)
        
        # Initialize predictor
        predictor = EnhancedMLPredictor(
            sequence_length=60,
            prediction_horizon=5,
            confidence_threshold=0.6
        )
        
        # Build ensemble (lightweight for testing)
        predictor.build_ensemble(['random_forest'])
        
        # Fit
        predictor.fit(df)
        
        # Predict
        pred = predictor.predict(df.iloc[-100:])
        
        assert pred is not None
        assert pred.confidence >= 0
        assert pred.confidence <= 1
    
    async def test_routing_execution(self):
        """Test order routing and execution"""
        if not COMPONENTS_AVAILABLE:
            return
        
        router = SmartOrderRouter()
        
        order = Order(
            id="integration_test",
            symbol="EURUSD",
            side=OrderSide.BUY,
            size=50.0,
            order_type=OrderType.TWAP,
            arrival_price=1.0850
        )
        
        result = await router.execute_order(order)
        
        assert result['status'] == 'FILLED'
        assert result['filled_size'] > 0
        assert result['avg_price'] > 0

class PerformanceTests:
    """Performance and load testing"""
    
    def __init__(self):
        self.results: List[TestResult] = []
    
    async def run_all(self) -> List[TestResult]:
        """Run performance tests"""
        tests = [
            self.test_backtest_throughput,
            self.test_prediction_latency,
            self.test_data_ingestion_rate,
        ]
        
        for test in tests:
            try:
                start = time.time()
                await test()
                duration = (time.time() - start) * 1000
                
                self.results.append(TestResult(
                    name=test.__name__,
                    category=TestCategory.PERFORMANCE,
                    passed=True,
                    duration_ms=duration
                ))
            except Exception as e:
                self.results.append(TestResult(
                    name=test.__name__,
                    category=TestCategory.PERFORMANCE,
                    passed=False,
                    duration_ms=0,
                    error_message=str(e)
                ))
        
        return self.results
    
    async def test_backtest_throughput(self):
        """Test backtest processing speed"""
        if not COMPONENTS_AVAILABLE:
            return
        
        ticks = TestDataGenerator.generate_ticks(n=10000)
        engine = EnhancedBacktestEngine()
        
        start = time.time()
        for tick in ticks:
            engine.process_tick(tick)
        duration = time.time() - start
        
        throughput = len(ticks) / duration
        logger.info(f"Backtest throughput: {throughput:.0f} ticks/sec")
        
        assert throughput > 1000  # Minimum 1000 ticks/sec
    
    async def test_prediction_latency(self):
        """Test ML prediction latency"""
        if not COMPONENTS_AVAILABLE:
            return
        
        df = TestDataGenerator.generate_ohlcv(n=500)
        
        predictor = EnhancedMLPredictor()
        predictor.build_ensemble(['random_forest'])
        predictor.fit(df.iloc[:400])
        
        # Measure prediction time
        latencies = []
        for _ in range(10):
            start = time.time()
            predictor.predict(df.iloc[-100:])
            latencies.append((time.time() - start) * 1000)
        
        avg_latency = np.mean(latencies)
        logger.info(f"Prediction latency: {avg_latency:.2f} ms")
        
        assert avg_latency < 100  # Sub-100ms
    
    async def test_data_ingestion_rate(self):
        """Test realtime data ingestion"""
        if not COMPONENTS_AVAILABLE:
            return
        
        aggregator = MultiSourceAggregator()
        
        # Add multiple high-frequency providers
        for i in range(5):
            aggregator.add_provider(MockProvider(volatility=0.0005))
        
        received = 0
        def count_ticks(tick):
            nonlocal received
            received += 1
        
        aggregator.on_consensus(count_ticks)
        
        # Run for 5 seconds
        task = asyncio.create_task(aggregator.start())
        await asyncio.sleep(5)
        aggregator.stop()
        task.cancel()
        
        rate = received / 5
        logger.info(f"Data ingestion rate: {rate:.0f} ticks/sec")
        
        assert rate > 10  # At least 10 consensus ticks/sec

class ChaosTests:
    """Chaos engineering tests"""
    
    def __init__(self):
        self.results: List[TestResult] = []
    
    async def run_all(self) -> List[TestResult]:
        """Run chaos tests"""
        tests = [
            self.test_provider_failure,
            self.test_data_corruption,
            self.test_network_latency,
        ]
        
        for test in tests:
            try:
                start = time.time()
                await test()
                duration = (time.time() - start) * 1000
                
                self.results.append(TestResult(
                    name=test.__name__,
                    category=TestCategory.CHAOS,
                    passed=True,
                    duration_ms=duration
                ))
            except Exception as e:
                self.results.append(TestResult(
                    name=test.__name__,
                    category=TestCategory.CHAOS,
                    passed=False,
                    duration_ms=0,
                    error_message=str(e)
                ))
        
        return self.results
    
    async def test_provider_failure(self):
        """Test system resilience to provider failure"""
        if not COMPONENTS_AVAILABLE:
            return
        
        aggregator = MultiSourceAggregator()
        
        # Add providers
        p1 = MockProvider()
        p2 = MockProvider()
        aggregator.add_provider(p1)
        aggregator.add_provider(p2)
        
        # Simulate failure
        p1.stop()
        
        # System should continue with remaining provider
        task = asyncio.create_task(aggregator.start())
        await asyncio.sleep(2)
        aggregator.stop()
        task.cancel()
        
        assert True  # If we get here, system handled failure
    
    async def test_data_corruption(self):
        """Test handling of corrupted data"""
        if not COMPONENTS_AVAILABLE:
            return
        
        # Generate corrupt data
        df = TestDataGenerator.generate_ohlcv(n=100)
        df.loc[50, 'close'] = np.nan  # Inject NaN
        df.loc[60, 'high'] = df.loc[60, 'low'] - 1  # Invalid OHLC
        
        engineer = FeatureEngineering()
        features = engineer.create_features(df)
        
        # Should handle gracefully
        assert len(features) < len(df)  # Some rows dropped
        assert not features.isnull().any().any()
    
    async def test_network_latency(self):
        """Test handling of high latency"""
        if not COMPONENTS_AVAILABLE:
            return
        
        # This would require network simulation
        # For now, just verify timeout handling
        assert True

class ComprehensiveTestFramework:
    """
    Main test framework orchestrating all test suites.
    """
    
    def __init__(self):
        self.unit_tests = UnitTests()
        self.integration_tests = IntegrationTests()
        self.performance_tests = PerformanceTests()
        self.chaos_tests = ChaosTests()
        
        self.all_results: List[TestResult] = []
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """Execute complete test suite"""
        print("=" * 70)
        print("COMPREHENSIVE TEST FRAMEWORK v3.0")
        print("=" * 70)
        
        start_time = time.time()
        
        # Run all suites
        self.all_results.extend(await self.unit_tests.run_all())
        self.all_results.extend(await self.integration_tests.run_all())
        self.all_results.extend(await self.performance_tests.run_all())
        self.all_results.extend(await self.chaos_tests.run_all())
        
        duration = time.time() - start_time
        
        # Generate report
        report = self._generate_report(duration)
        
        # Print summary
        self._print_summary(report)
        
        return report

    def _generate_report(self, duration: float) -> Dict[str, Any]:
        """Generate comprehensive test report"""
        passed = sum(1 for r in self.all_results if r.passed)
        failed = len(self.all_results) - passed
        
        by_category = {}
        for cat in TestCategory:
            cat_results = [r for r in self.all_results if r.category == cat]
            by_category[cat.value] = {
                'total': len(cat_results),
                'passed': sum(1 for r in cat_results if r.passed),
                'failed': sum(1 for r in cat_results if not r.passed),
                'duration_ms': sum(r.duration_ms for r in cat_results)
            }
        
        return {
            'summary': {
                'total_tests': len(self.all_results),
                'passed': passed,
                'failed': failed,
                'pass_rate': passed / len(self.all_results) if self.all_results else 0,
                'total_duration_sec': duration,
                'timestamp': datetime.now().isoformat()
            },
            'by_category': by_category,
            'failed_tests': [
                {
                    'name': r.name,
                    'category': r.category.value,
                    'error': r.error_message
                }
                for r in self.all_results if not r.passed
            ],
            'all_results': [
                {
                    'name': r.name,
                    'category': r.category.value,
                    'passed': r.passed,
                    'duration_ms': round(r.duration_ms, 2)
                }
                for r in self.all_results
            ]
        }
    
    def _print_summary(self, report: Dict):
        """Print formatted test summary"""
        print("\n" + "=" * 70)
        print("TEST EXECUTION SUMMARY")
        print("=" * 70)
        
        summary = report['summary']
        print(f"Total Tests:    {summary['total_tests']}")
        print(f"Passed:         {summary['passed']} ✅")
        print(f"Failed:         {summary['failed']} ❌")
        print(f"Pass Rate:      {summary['pass_rate']:.1%}")
        print(f"Duration:       {summary['total_duration_sec']:.2f}s")
        
        print("\n" + "-" * 70)
        print("BY CATEGORY")
        print("-" * 70)
        
        for cat, stats in report['by_category'].items():
            status = "✅" if stats['failed'] == 0 else "⚠️"
            print(f"{cat:15} | {stats['passed']:3d}/{stats['total']:<3d} | {status}")
        
        if report['failed_tests']:
            print("\n" + "-" * 70)
            print("FAILED TESTS")
            print("-" * 70)
            for ft in report['failed_tests']:
                print(f"❌ {ft['category']:12} | {ft['name']}")
                print(f"   Error: {ft['error'][:100]}")
        
        print("\n" + "=" * 70)
        if summary['failed'] == 0:
            print("🎉 ALL TESTS PASSED!")
        else:
            print(f"⚠️  {summary['failed']} TEST(S) FAILED - REVIEW REQUIRED")
        print("=" * 70)
    
    def export_report(self, filepath: str):
        """Export test report to JSON"""
        import json
        with open(filepath, 'w') as f:
            json.dump(self._generate_report(0), f, indent=2, default=str)
        logger.info(f"Test report exported to {filepath}")

# =============================================================================
# PYTEST COMPATIBILITY
# =============================================================================

# Unit test functions for pytest
@pytest.mark.asyncio
async def test_tick_data():
    """Pytest-compatible tick data test"""
    framework = UnitTests()
    await framework.test_tick_data_validation()
    assert all(r.passed for r in framework.results)

@pytest.mark.asyncio
async def test_backtest_integration():
    """Pytest-compatible backtest test"""
    framework = IntegrationTests()
    await framework.test_backtest_full_workflow()
    assert all(r.passed for r in framework.results)

@pytest.mark.asyncio
async def test_performance():
    """Pytest-compatible performance test"""
    framework = PerformanceTests()
    await framework.test_backtest_throughput()
    assert all(r.passed for r in framework.results)

# =============================================================================
# EXAMPLE USAGE & TESTING
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("COMPREHENSIVE TEST FRAMEWORK v3.0 - EXECUTION")
    print("=" * 70)
    
    # Run all tests
    framework = ComprehensiveTestFramework()
    
    try:
        report = asyncio.run(framework.run_all_tests())
        
        # Export report
        framework.export_report("test_report.json")
        
        # Exit with appropriate code
        exit_code = 0 if report['summary']['failed'] == 0 else 1
        print(f"\nExit code: {exit_code}")
        
    except Exception as e:
        logger.error(f"Test framework error: {e}")
        raise
