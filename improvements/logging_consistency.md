# Logging Consistency Guidelines

## Purpose
The purpose of these guidelines is to ensure that all logging across the HOPEFX-AI-TRADING project is done in a consistent manner to promote clarity, maintainability, and ease of debugging.

## General Guidelines
1. **Standard Format**: All log messages should follow a standard format:
   - Include a timestamp.
   - Include the log level (INFO, DEBUG, WARNING, ERROR, CRITICAL).
   - Include a clear and concise message.
   - Optionally, include any relevant identifiers (e.g., user IDs, transaction IDs).
2. **Log Levels**:
   - Use appropriate log levels for different situations:
     - **DEBUG**: Detailed information for diagnosing issues.
     - **INFO**: General information related to application progress.
     - **WARNING**: Indication of something unexpected, but the application is still functioning.
     - **ERROR**: An error occurred, but the application can still continue running.
     - **CRITICAL**: A serious error that may prevent the application from continuing.
3. **Contextual Information**: Whenever possible, include contextual information that may assist in understanding the log message.
4. **Avoid Sensitive Data**: Never log sensitive information (e.g., passwords, personal data). Always sanitize inputs before logging.

## Implementation Tips
- Use structured logging whenever possible (e.g., JSON format) to make it easier to parse and analyze logs.
- Set up a log rotation policy to manage log file sizes and archival.
- Implement a centralized logging solution if the project scales significantly, to aggregate logs from multiple services.

## Example Log Messages
- **INFO**: `2026-03-22 09:21:47 [INFO] User login successful: user_id=123
- **ERROR**: `2026-03-22 09:21:47 [ERROR] Failed to process transaction: transaction_id=789

By following these guidelines, we can ensure our logging is effective and serves its purpose in supporting the development and operation of HOPEFX-AI-TRADING.