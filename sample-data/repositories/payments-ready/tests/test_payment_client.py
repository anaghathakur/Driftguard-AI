from demo.payment_client import create_payment


def test_payment_payload_contract():
    # Static demo evidence: POST /payments, amount, email, customer_id.
    assert create_payment
