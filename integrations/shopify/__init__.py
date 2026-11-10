"""Shopify, stood alone. Velvet over concrete.

The store talks to one client now, and one client only: this one.
No Replit in the middle, no WealthArchitectBot in the middle, no
token pasted in a chat. The token lives in the environment and
nowhere else, and the code never prints it, never logs it, never
saves it.

Love is a liability. Style is armor. Receipts for every job.
"""
from .shopify_client import ShopifyClient, ShopifyWriteDisabledError

__all__ = ["ShopifyClient", "ShopifyWriteDisabledError"]
