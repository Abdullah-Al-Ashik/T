from src.retry_manager import retry_delay_seconds, is_permanent_error

class Permanent(Exception):
    retryable = False

def test_exponential_retry_is_capped():
    assert retry_delay_seconds(1, 30, 100) == 30
    assert retry_delay_seconds(2, 30, 100) == 60
    assert retry_delay_seconds(9, 30, 100) == 100

def test_permanent_error_classification():
    assert is_permanent_error(Permanent())
    assert not is_permanent_error(RuntimeError("network"))
