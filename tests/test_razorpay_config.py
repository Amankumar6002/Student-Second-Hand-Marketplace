from pathlib import Path


def test_env_example_contains_razorpay_placeholders():
    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    text = env_example.read_text(encoding="utf-8")

    assert "RAZORPAY_KEY_ID" in text
    assert "RAZORPAY_KEY_SECRET" in text
    assert "rzp_test_" in text
    assert "your_test_secret" in text.lower()
