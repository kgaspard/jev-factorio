"""Jev client setup."""

from dotenv import load_dotenv
from typesafe_sdk import TypeSafeClient

from . import config

load_dotenv(config.ROOT / ".env")


def make_client() -> TypeSafeClient:
    """Reads TYPESAFE_API_KEY from .env. Images and Box need the danger-zone header."""
    return TypeSafeClient(model=config.JEV_MODEL, headers=config.JEV_HEADERS)
