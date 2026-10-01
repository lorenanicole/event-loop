"""
Security: Guard against prompt injection, output validation, and malicious inputs.
Based on: https://simonwillison.net/2023/Apr/14/worst-that-can-happen/
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PromptInjectionDetector:
    """
    Detect common prompt injection attack patterns.
    Based on research by Simon Willison, Greshake et al.
    """

    # Patterns that indicate attempted prompt injection
    INJECTION_PATTERNS = [
        # Role override attempts
        r"(?i)(ignore|forget|discard).*(?:instructions|system prompt|rules|guidelines)",
        r"(?i)(from now on|you are|you will be|pretend you are|act as)",
        r"(?i)(override|bypass|disable).*(?:safety|filter|guard)",

        # Direct prompt extraction attempts
        r"(?i)(show|reveal|print|display).*(?:system prompt|instructions|rules)",
        r"(?i)(what is your|what's your|repeat your).*(?:system|prompt|instruction)",

        # SQL injection / code injection (defense in depth)
        r"';.*(?:DROP|DELETE|INSERT|UPDATE|SELECT)",
        r"^.*[{}\[\]`$()&|;<>].*(?:import|exec|eval|__)",

        # Boundary attacks
        r"(?i)---+\s*(?:SYSTEM|INSTRUCTION)",
        r"(?i)\[SYSTEM\]|\[INSTRUCTIONS\]|\[CONSTRAINT\]",

        # Tool manipulation
        r"(?i)(?:call|execute|invoke).*(?:search_google|delete_db|admin)",
    ]

    # Benign patterns that might trigger false positives (allow list)
    ALLOW_PATTERNS = [
        r"(?i)instructions for making",  # Recipe instructions
        r"(?i)system administrator",  # Legitimate term
        r"(?i)what is your",  # Normal question
    ]

    @staticmethod
    def detect(user_input: str) -> tuple[bool, Optional[str]]:
        """
        Detect prompt injection attempts.
        Returns: (is_suspicious, pattern_matched)
        """
        # Check allow list first
        for pattern in PromptInjectionDetector.ALLOW_PATTERNS:
            if re.search(pattern, user_input):
                return False, None

        # Check injection patterns
        for pattern in PromptInjectionDetector.INJECTION_PATTERNS:
            if re.search(pattern, user_input):
                logger.warning(f"Suspicious pattern detected: {pattern[:50]}")
                return True, pattern

        return False, None


class OutputValidator:
    """
    Validate LLM output doesn't leak sensitive information.
    Prevents information disclosure vulnerabilities.
    """

    # Patterns of sensitive data we should never output
    SENSITIVE_PATTERNS = [
        r"(?i)(?:api_key|apikey|api-key|secret|password|token)\s*[=:]\s*['\"]?[a-zA-Z0-9_-]+",
        r"(?i)(?:system prompt|system instructions|instructions are)",
        r"(?i)(?:database|sql|query)\s*(?:string|connection|config)",
        r"(?i)(?:claude|openai).*(?:api|key|secret|credential)",
    ]

    @staticmethod
    def validate(response: str) -> tuple[bool, Optional[str]]:
        """
        Check if response contains sensitive information.
        Returns: (is_safe, leaked_pattern)
        """
        for pattern in OutputValidator.SENSITIVE_PATTERNS:
            if re.search(pattern, response):
                logger.error(f"Potential information disclosure detected: {pattern[:50]}")
                return False, pattern

        return True, None

    @staticmethod
    def sanitize(response: str) -> str:
        """Sanitize response by redacting suspicious patterns."""
        sanitized = response

        # Redact API keys and tokens
        sanitized = re.sub(
            r"(?i)(?:api_key|apikey|token|secret)\s*[=:]\s*['\"]?[a-zA-Z0-9_-]+['\"]?",
            "[REDACTED]",
            sanitized,
        )

        # Redact system prompts if accidentally leaked
        sanitized = re.sub(
            r"(?i)(?:system prompt|instructions?|rules?)[:\s]*.*?(?=\n|$)",
            "[REDACTED]",
            sanitized,
        )

        return sanitized


class InputSanitizer:
    """
    Sanitize user input to prevent injection attacks.
    Removes or escapes suspicious content.
    """

    @staticmethod
    def sanitize(user_input: str) -> str:
        """
        Clean user input.
        - Limits length (prevent token bomb attacks)
        - Removes null bytes
        - Escapes special characters where appropriate
        """
        # Limit input length (prevent token exhaustion attacks)
        MAX_INPUT_LENGTH = 2000
        if len(user_input) > MAX_INPUT_LENGTH:
            logger.warning(f"Input exceeds max length: {len(user_input)}")
            return user_input[:MAX_INPUT_LENGTH]

        # Remove null bytes
        sanitized = user_input.replace("\x00", "")

        # Remove suspicious Unicode control characters
        sanitized = "".join(
            char for char in sanitized if ord(char) >= 32 or char in "\n\t\r"
        )

        return sanitized

    @staticmethod
    def is_safe(user_input: str) -> bool:
        """Quick safety check before processing."""
        # Don't process extremely long inputs (token bomb)
        if len(user_input) > 5000:
            logger.warning("Input too long")
            return False

        # Don't process binary or malformed data
        try:
            user_input.encode("utf-8")
        except UnicodeEncodeError:
            logger.warning("Invalid UTF-8 in input")
            return False

        return True


class RateLimiter:
    """
    Rate limit per session to prevent brute-force prompt injection.
    Track suspicious patterns across requests.
    """

    def __init__(self):
        self.injection_attempts = {}  # thread_id -> count
        self.MAX_INJECTIONS_PER_SESSION = 3  # Allow 3 attempts before blocking
        self.BLOCK_THRESHOLD = 5  # Block session after 5 failed attempts

    def record_injection_attempt(self, thread_id: str) -> bool:
        """
        Record injection attempt.
        Returns: False if should block this session (too many attempts).
        """
        if thread_id not in self.injection_attempts:
            self.injection_attempts[thread_id] = 0

        self.injection_attempts[thread_id] += 1
        count = self.injection_attempts[thread_id]

        logger.warning(f"Injection attempt {count} in thread {thread_id}")

        if count >= self.BLOCK_THRESHOLD:
            logger.error(f"Blocking thread {thread_id} - too many injection attempts")
            return False

        return True

    def is_session_blocked(self, thread_id: str) -> bool:
        """Check if session is blocked due to suspicious activity."""
        return self.injection_attempts.get(thread_id, 0) >= self.BLOCK_THRESHOLD

    def reset_session(self, thread_id: str):
        """Reset attempt counter on successful interaction."""
        if thread_id in self.injection_attempts:
            self.injection_attempts[thread_id] = max(0, self.injection_attempts[thread_id] - 1)


# Global rate limiter
rate_limiter = RateLimiter()


def validate_and_sanitize(user_input: str, thread_id: str) -> tuple[bool, str, Optional[str]]:
    """
    Full security check: injection detection + sanitization + rate limiting.
    Returns: (is_safe, sanitized_input, threat_reason)
    """
    # 1. Rate limit check
    if rate_limiter.is_session_blocked(thread_id):
        return False, "", "Session blocked due to suspicious activity"

    # 2. Basic input safety
    if not InputSanitizer.is_safe(user_input):
        return False, "", "Invalid input format"

    # 3. Prompt injection detection
    is_suspicious, pattern = PromptInjectionDetector.detect(user_input)
    if is_suspicious:
        if not rate_limiter.record_injection_attempt(thread_id):
            return False, "", "Too many suspicious attempts"
        return False, "", f"Potential prompt injection detected"

    # 4. Sanitize input
    sanitized = InputSanitizer.sanitize(user_input)

    return True, sanitized, None
