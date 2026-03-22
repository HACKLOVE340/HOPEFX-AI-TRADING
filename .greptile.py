{
  "remoteRepo": "HACKLOVE340/HOPEFX-AI-TRADING",
  "strictness": 3,
  "commentTypes": ["logic", "security", "performance"],
  "customInstructions": [
    "AUDIT FOR FINANCIAL RISK: Identify any function that sends a trade order (mt5.order_send) without a hard-coded or calculated Stop Loss (SL).",
    "AUDIT FOR VOIDS: List every file that is empty or contains only boilerplate code with no functional logic.",
    "AUDIT FOR SECURITY: Flag any hard-coded strings that look like API Keys, account numbers, or passwords.",
    "AUDIT FOR CONNECTIVITY: Check if there is a 'reconnection' logic if the MetaTrader 5 terminal or the Internet disconnects.",
    "AUDIT FOR AI HALLUCINATION: Ensure that AI-generated trade signals are validated (e.g., checking if the price is a valid number) before being sent to the broker."
  ],
  "ignorePatterns": ["**/venv/**", "**/.git/**", "**/__pycache__/**"]
}
