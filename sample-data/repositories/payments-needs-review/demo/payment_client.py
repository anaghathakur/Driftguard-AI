"""Direct Payments API client used by the deterministic DriftGuard demo."""

import requests


def create_payment(base_url, amount, email):
    payload = {
        "amount": amount,
        "email": email,
    }
    return requests.post(f"{base_url}/payments", json=payload, timeout=10)
