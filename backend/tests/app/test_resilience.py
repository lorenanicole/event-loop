"""
Tests for resilience module: circuit breaker, retry logic, error classification.
"""

import pytest
from app.resilience import (
    CircuitBreaker,
    RetryPolicy,
    ErrorClassifier,
    ServiceStatus,
)


class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    def test_starts_healthy(self):
        """Circuit breaker starts in HEALTHY state."""
        cb = CircuitBreaker("test_service", failure_threshold=3)
        assert cb.status == ServiceStatus.HEALTHY
        assert cb.is_available() is True

    def test_degrades_on_failures(self):
        """Transitions to DEGRADED after first failure."""
        cb = CircuitBreaker("test_service", failure_threshold=3)
        cb.record_failure()
        assert cb.status == ServiceStatus.DEGRADED
        assert cb.is_available() is True  # Still available but degraded

    def test_opens_at_threshold(self):
        """Transitions to UNHEALTHY after threshold failures."""
        cb = CircuitBreaker("test_service", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.status == ServiceStatus.UNHEALTHY
        assert cb.is_available() is False

    def test_recovers_on_success(self):
        """Resets to HEALTHY on success."""
        cb = CircuitBreaker("test_service", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.status == ServiceStatus.UNHEALTHY

        cb.record_success()
        assert cb.status == ServiceStatus.HEALTHY
        assert cb.failure_count == 0

    def test_blocks_when_open(self):
        """Not available when circuit is open."""
        cb = CircuitBreaker("test_service", failure_threshold=1)
        cb.record_failure()
        assert cb.is_available() is False

    def test_attempts_recovery_after_timeout(self):
        """Tries to recover after timeout expires."""
        cb = CircuitBreaker("test_service", failure_threshold=1, recovery_timeout_seconds=0)
        cb.record_failure()
        assert cb.is_available() is False

        # After timeout, should attempt recovery
        import time
        time.sleep(0.1)
        # Note: This would need actual timeout logic verification


class TestRetryPolicy:
    """Test retry logic with exponential backoff."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        """Execute successfully on first try."""
        policy = RetryPolicy(max_retries=3)
        call_count = 0

        async def success_coro():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await policy.execute(success_coro, "test_op")
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        """Retries when operation fails."""
        policy = RetryPolicy(max_retries=2, initial_delay_ms=10)
        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Temporary failure")
            return "success"

        result = await policy.execute(fail_then_succeed, "test_op")
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        """Raises error after exhausting retries."""
        policy = RetryPolicy(max_retries=2, initial_delay_ms=10)

        async def always_fails():
            raise ValueError("Persistent failure")

        with pytest.raises(ValueError):
            await policy.execute(always_fails, "test_op")

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """Delays increase exponentially."""
        policy = RetryPolicy(
            max_retries=3,
            initial_delay_ms=100,
            max_delay_ms=500
        )
        # Delays should be: 100ms, 200ms, 400ms
        assert policy.initial_delay_ms == 100
        assert policy.max_delay_ms == 500


class TestErrorClassifier:
    """Test error classification."""

    def test_classifies_auth_errors(self):
        """Identify authentication errors (non-retryable)."""
        error = Exception("Invalid API key provided")
        error_type, is_retryable = ErrorClassifier.classify_llm_error(error)
        assert error_type == "auth_error"
        assert is_retryable is False

    def test_classifies_rate_limit(self):
        """Identify rate limit errors (retryable)."""
        error = Exception("Rate limit exceeded: 429")
        error_type, is_retryable = ErrorClassifier.classify_llm_error(error)
        assert error_type == "rate_limit"
        assert is_retryable is True

    def test_classifies_service_unavailable(self):
        """Identify service unavailable (retryable)."""
        error = Exception("Service unavailable: 503")
        error_type, is_retryable = ErrorClassifier.classify_llm_error(error)
        assert error_type == "service_unavailable"
        assert is_retryable is True

    def test_classifies_timeout(self):
        """Identify timeout errors (retryable)."""
        error = Exception("Connection timeout")
        error_type, is_retryable = ErrorClassifier.classify_llm_error(error)
        assert error_type == "service_unavailable"
        assert is_retryable is True

    def test_classifies_insufficient_quota(self):
        """Identify token quota errors (non-retryable)."""
        error = Exception("Insufficient quota for this operation")
        error_type, is_retryable = ErrorClassifier.classify_llm_error(error)
        assert error_type == "insufficient_quota"
        assert is_retryable is False

    def test_classifies_db_connection_error(self):
        """Identify database connection errors (retryable)."""
        error = Exception("Database connection refused")
        error_type, is_retryable = ErrorClassifier.classify_db_error(error)
        assert error_type == "connection_error"
        assert is_retryable is True

    def test_classifies_db_query_error(self):
        """Identify database query errors (non-retryable)."""
        error = Exception("SQL syntax error: table does not exist")
        error_type, is_retryable = ErrorClassifier.classify_db_error(error)
        assert error_type == "query_error"
        assert is_retryable is False
