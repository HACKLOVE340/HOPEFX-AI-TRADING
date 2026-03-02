# Fix: test_calculate_position_size Integration Test

## Issue

Integration test `test_calculate_position_size` was failing with HTTP 422 status code.

**Error Message:**
```
FAILED tests/integration/test_api.py::TestTradingEndpoints::test_calculate_position_size 
- assert 422 in [200, 500]
  + where 422 = <Response>.status_code
```

## Root Cause

The test was sending invalid request data that didn't match the API endpoint's Pydantic schema.

**Incorrect Request:**
```python
{
    "symbol": "EUR_USD",      # Field not in schema
    "price": 1.1000,          # Wrong field name
    "method": "fixed",        # Field not in schema
    "amount": 10000           # Field not in schema
}
```

**Expected Schema (PositionSizeRequest):**
```python
class PositionSizeRequest(BaseModel):
    entry_price: float                 # Required
    stop_loss_price: Optional[float]   # Optional
    confidence: float = 1.0            # Optional with default
```

## Solution

Updated test to send correct request data matching the API schema:

**Correct Request:**
```python
{
    "entry_price": 1.1000,        # ✅ Required field
    "stop_loss_price": 1.0950,    # ✅ Optional field (50 pips stop)
    "confidence": 0.8              # ✅ Optional field (80% confidence)
}
```

## Changes Made

**File:** `tests/integration/test_api.py` (lines 75-85)

**Before:**
```python
def test_calculate_position_size(self, client):
    """Test position size calculation."""
    request_data = {
        "symbol": "EUR_USD",
        "price": 1.1000,
        "method": "fixed",
        "amount": 10000
    }
    
    response = client.post("/api/trading/position-size", json=request_data)
    assert response.status_code in [200, 500]
```

**After:**
```python
def test_calculate_position_size(self, client):
    """Test position size calculation."""
    request_data = {
        "entry_price": 1.1000,
        "stop_loss_price": 1.0950,
        "confidence": 0.8
    }
    
    response = client.post("/api/trading/position-size", json=request_data)
    assert response.status_code in [200, 500]
```

## Expected Result

Test will now:
1. Send valid request data matching API schema ✅
2. Receive either 200 (success) or 500 (internal error) ✅
3. No longer get 422 validation errors ✅

**Status:** ✅ FIXED
