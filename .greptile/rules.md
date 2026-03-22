# Global Trading App Standards

## 1. Zero Tolerance for Empty Logic
- **Rule:** Any file that is imported by another file must contain functional code.
- **Action:** Flag any file that only contains comments or is 0KB as a "Critical Block."

## 2. Financial Safety (The "Stop Loss" Rule)
- **Rule:** Every call to `mt5.order_send` must be preceded by a validation of the `sl` (Stop Loss) parameter.
- **Action:** If `sl` is 0, None, or missing, mark the PR as "Unsafe for Live."

## 3. Secret Management
- **Rule:** No plaintext strings that match account numbers, passwords, or API keys.
- **Action:** Check for patterns like `key = "..."` or `password = "..."`. Demand the use of `os.getenv()`.

## 4. Connectivity Resilience
- **Rule:** All network calls (MT5 or AI APIs) must be wrapped in `try-except` blocks.
- **Action:** Flag "Naked" API calls that don't handle `ConnectionError` or `Timeout`.
