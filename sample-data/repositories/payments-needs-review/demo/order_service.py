"""Transitive caller used to demonstrate the dependency chain."""

from .checkout import checkout


def submit_order(order):
    return checkout(order)
