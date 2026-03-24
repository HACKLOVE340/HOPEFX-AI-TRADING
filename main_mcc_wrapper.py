"""
DEPRECATED — do not use.

This file is kept for git history only. The canonical entry point is app.py.
MCC integration is handled by brain/brain.py, wired at startup in app.py.

    uvicorn app:app --host 0.0.0.0 --port 8000
"""
import sys

if __name__ == "__main__":
    print("ERROR: main_mcc_wrapper.py is deprecated. Use: uvicorn app:app --host 0.0.0.0 --port 8000")
    sys.exit(1)
