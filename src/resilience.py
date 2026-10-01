"""
Resilience patterns: circuit breaker, retry logic, graceful degradation.
Handles LLM failures, database unavailability, and rate limiting.
"""

from enum import Enum
from datetime import datetime, timedelta
import logging
import asyncio

logger = logging.getLogger(__name__)


class ServiceStatus(Enum):
    """Circuit breaker states."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class CircuitBreaker:
    """
    Circuit breaker for failing services.
    Prevents hammering a failing LLM or database.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout_seconds: int = 60,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = timedelta(seconds=recovery_timeout_seconds)
        self.failure_count = 0
        self.last_failure_time: datetime | None = None
        self.status = ServiceStatus.HEALTHY

    def record_success(self):
        """Reset on success."""
        self.failure_count = 0
        self.status = ServiceStatus.HEALTHY
        logger.info(f"CircuitBreaker({self.name}): Recovered to HEALTHY")

    def record_failure(self):
        """Increment failure count."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()

        if self.failure_count >= self.failure_threshold:
            self.status = ServiceStatus.UNHEALTHY
            logger.warning(
                f"CircuitBreaker({self.name}): UNHEALTHY (failures: {self.failure_count})"
            )
        else:
            self.status = ServiceStatus.DEGRADED
            logger.warning(
                f"CircuitBreaker({self.name}): DEGRADED (failures: {self.failure_count}/{self.failure_threshold})"
            )

    def is_available(self) -> bool:
        """Check if service is available."""
        if self.status == ServiceStatus.HEALTHY:
            return True

        if self.status == ServiceStatus.UNHEALTHY:
            # Try recovery after timeout
            if self.last_failure_time:
                if datetime.utcnow() >= self.last_failure_time + self.recovery_timeout:
                    logger.info(f"CircuitBreaker({self.name}): Attempting recovery...")
                    self.failure_count = 0
                    self.status = ServiceStatus.DEGRADED
                    return True
            return False

        return True  # DEGRADED - allow with caution


class RetryPolicy:
    """Exponential backoff retry logic."""

    def __init__(
        self,
        max_retries: int = 3,
        initial_delay_ms: int = 100,
        max_delay_ms: int = 5000,
    ):
        self.max_retries = max_retries
        self.initial_delay_ms = initial_delay_ms
        self.max_delay_ms = max_delay_ms

    async def execute(self, coro, operation_name: str = "operation"):
        """Execute coroutine with exponential backoff."""
        delay_ms = self.initial_delay_ms

        for attempt in range(self.max_retries + 1):
            try:
                return await coro
            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(
                        f"Retry {attempt + 1}/{self.max_retries} for {operation_name}: {str(e)}"
                    )
                    await asyncio.sleep(delay_ms / 1000.0)
                    delay_ms = min(delay_ms * 2, self.max_delay_ms)  # Exponential backoff
                else:
                    logger.error(
                        f"All retries exhausted for {operation_name}: {str(e)}"
                    )
                    raise


class ErrorClassifier:
    """Distinguish between transient and permanent failures."""

    @staticmethod
    def classify_llm_error(error: Exception) -> tuple[str, bool]:
        """
        Classify LLM error.
        Returns: (error_type, is_retryable)
        """
        error_str = str(error).lower()

        # Authentication/Authorization errors (permanent)
        if any(x in error_str for x in ["invalid_api_key", "unauthorized", "403", "401"]):
            return ("auth_error", False)

        # Rate limiting (transient)
        if any(x in error_str for x in ["rate_limit", "429", "quota"]):
            return ("rate_limit", True)

        # Service unavailable (transient)
        if any(x in error_str for x in ["unavailable", "503", "timeout", "connection"]):
            return ("service_unavailable", True)

        # Out of tokens (permanent for this request)
        if any(x in error_str for x in ["insufficient_quota", "token", "max_tokens"]):
            return ("insufficient_quota", False)

        # Unknown (assume transient)
        return ("unknown", True)

    @staticmethod
    def classify_db_error(error: Exception) -> tuple[str, bool]:
        """
        Classify database error.
        Returns: (error_type, is_retryable)
        """
        error_str = str(error).lower()

        # Connection errors (transient)
        if any(
            x in error_str
            for x in ["connection", "timeout", "pool", "connect", "refused"]
        ):
            return ("connection_error", True)

        # Query errors (permanent)
        if any(x in error_str for x in ["syntax", "invalid", "does not exist"]):
            return ("query_error", False)

        # Unknown (assume transient)
        return ("unknown", True)


# Global circuit breakers
llm_circuit_breaker = CircuitBreaker(
    name="claude_llm",
    failure_threshold=5,
    recovery_timeout_seconds=60,
)

db_circuit_breaker = CircuitBreaker(
    name="sqlite_db",
    failure_threshold=10,
    recovery_timeout_seconds=30,
)

# Global retry policy
default_retry_policy = RetryPolicy(max_retries=3, initial_delay_ms=100)
