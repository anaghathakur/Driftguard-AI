"""Caller corrected for the V2 customer identifier before validation."""

from .payment_client import create_payment


def checkout(order):
    return create_payment(order.base_url, order.amount, order.customer_id)
