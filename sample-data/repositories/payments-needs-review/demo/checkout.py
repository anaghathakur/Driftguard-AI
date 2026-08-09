"""Caller that intentionally retains the removed email value."""

from .payment_client import create_payment


def checkout(order):
    return create_payment(order.base_url, order.amount, order.email)
