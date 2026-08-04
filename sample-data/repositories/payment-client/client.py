"""Minimal client used for the repository-impact Swagger demo."""

import requests


def create_payment(base_url: str, payload: dict[str, object]) -> dict[str, object]:
    response = requests.post(f"{base_url}/payments", json=payload, timeout=10)
    response.raise_for_status()
    return response.json()
