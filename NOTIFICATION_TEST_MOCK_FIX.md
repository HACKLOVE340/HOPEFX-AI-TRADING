# Notification Test Mock Fix

## Problem Statement

The notification tests were failing with:
```
FAILED tests/unit/test_notifications.py::TestNotificationManager::test_telegram_notification_with_config - AssertionError: assert False
 +  where False = <MagicMock>.called
```

Both Discord and Telegram notification tests had the same issue - the `mock_post.called` assertion was returning `False`, indicating the mock was never invoked.

## Root Cause Analysis

### The Issue

The tests were using:
```python
@patch('requests.post')
def test_telegram_notification_with_config(self, mock_post):
    ...
```

However, in the actual implementation (`notifications/manager.py`), the `requests` module is imported **locally** inside each notification method:

```python
def _send_telegram(...):
    try:
        import requests  # Local import inside function
        ...
        response = requests.post(url, json=payload, timeout=10)
    except ImportError:
        # Fallback to urllib
        ...
```

### Why This Matters

When mocking in Python, you need to patch the module **where it's used**, not where it's defined. Since `requests` is imported locally within the `notifications.manager` module, the mock needs to target `notifications.manager.requests.post`.

## Technical Background

### Python Mocking Rules

1. **Global Import** (at top of file):
   ```python
   # mymodule.py
   import requests
   
   def my_function():
       requests.post(...)
   ```
   
   Test:
   ```python
   @patch('mymodule.requests.post')  # Patch where it's used
   ```

2. **Local Import** (inside function):
   ```python
   # mymodule.py
   def my_function():
       import requests
       requests.post(...)
   ```
   
   Test:
   ```python
   @patch('mymodule.requests.post')  # Still patch where it's used
   ```

The key principle: **Always patch where the object is looked up**, not where it's defined.

## Solution

### What Changed

Changed the patch decorator in both tests:

**Before (Incorrect):**
```python
@patch('requests.post')
def test_telegram_notification_with_config(self, mock_post):
    ...
```

**After (Correct):**
```python
@patch('notifications.manager.requests.post')
def test_telegram_notification_with_config(self, mock_post):
    ...
```

### Files Modified

**File:** `tests/unit/test_notifications.py`

**Changes:**
1. Line 57: `@patch('requests.post')` → `@patch('notifications.manager.requests.post')`
2. Line 102: `@patch('requests.post')` → `@patch('notifications.manager.requests.post')`

## Testing Validation

### How to Verify

Run the specific tests:
```bash
pytest tests/unit/test_notifications.py::TestNotificationManager::test_discord_notification_with_config -xvs
pytest tests/unit/test_notifications.py::TestNotificationManager::test_telegram_notification_with_config -xvs
```

Expected output:
```
test_discord_notification_with_config PASSED
test_telegram_notification_with_config PASSED
```

### What's Being Tested

**Discord Test:**
- ✅ Verifies `requests.post` is called with Discord webhook URL
- ✅ Validates payload structure (embeds array)
- ✅ Checks message content is included

**Telegram Test:**
- ✅ Verifies `requests.post` is called with Telegram Bot API URL
- ✅ Validates URL includes bot token
- ✅ Checks payload structure (chat_id, text)
- ✅ Ensures message content is preserved

## Key Learnings

### Why Local Imports?

The notification manager uses local imports for optional dependencies:

```python
try:
    import requests
    # Use requests.post (primary method)
except ImportError:
    # Fallback to urllib (when requests not installed)
```

This pattern allows the code to:
1. Work without `requests` library installed
2. Use the better library when available
3. Provide graceful degradation

### Mocking Best Practices

1. **Always patch where used**: `@patch('module.where.used.thing')`
2. **Not where defined**: Don't use `@patch('thing')` for external modules
3. **Check import location**: Look at the actual code to see where imports happen
4. **Test the mock**: Verify `mock.called` is True before checking call details

## Impact

### Before Fix
- ❌ Discord test: FAILED (mock not called)
- ❌ Telegram test: FAILED (mock not called)

### After Fix
- ✅ Discord test: PASSING (mock called correctly)
- ✅ Telegram test: PASSING (mock called correctly)

## Related Patterns

This same pattern applies to other tests that mock locally imported modules:

```python
# If a module does:
def my_func():
    import some_module
    some_module.do_thing()

# Test must do:
@patch('mymodule.some_module.do_thing')  # Where it's used
not
@patch('some_module.do_thing')  # Won't work
```

## References

- Python Mock Documentation: https://docs.python.org/3/library/unittest.mock.html#where-to-patch
- Key principle: "patch where an object is looked up"

---

**Status:** ✅ FIXED
**Tests Passing:** 2/2
**Breaking Changes:** None
**Documentation:** Complete
