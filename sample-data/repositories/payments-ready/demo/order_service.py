"""Transitive caller intentionally left without a directly related test."""

from .checkout import checkout


def submit_order(order):
    return checkout(order)
