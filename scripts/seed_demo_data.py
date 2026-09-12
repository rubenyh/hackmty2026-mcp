"""Idempotent seeder for the demo banking schema.

Populates seeded (never real) users, accessibility preferences, accounts,
transactions, and subscriptions covering the initial UX scenarios from
PROJECT_SPEC.MD: a liquidity crisis, a subscription review, and a purchase
simulation with an accessible-reading-mode profile.

Writes through the Supabase service-role key, which bypasses RLS. Every row
uses a UUID derived deterministically from a stable slug (uuid5), so re-running
this script upserts the same rows instead of duplicating them.

Usage:
    .venv/bin/python scripts/seed_demo_data.py
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, create_client

NAMESPACE = uuid.UUID("6f1b1a2e-3c9e-4b7d-9f0a-2f6d0c9e5a11")


def stable_id(slug: str) -> str:
    """Derive a deterministic UUID so reseeding never creates duplicate rows."""
    return str(uuid.uuid5(NAMESPACE, slug))


def days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


ANA_ID = stable_id("user:ana_garcia")
LUIS_ID = stable_id("user:luis_torres")
SOFIA_ID = stable_id("user:sofia_ramirez")

ANA_ACCOUNT_ID = stable_id("account:ana_garcia:checking")
LUIS_ACCOUNT_ID = stable_id("account:luis_torres:checking")
SOFIA_ACCOUNT_ID = stable_id("account:sofia_ramirez:savings")

USERS = [
    {
        "id": ANA_ID,
        "display_name": "Ana García",
        "email": "ana.demo@fluidbank.test",
        "is_demo": True,
    },
    {
        "id": LUIS_ID,
        "display_name": "Luis Torres",
        "email": "luis.demo@fluidbank.test",
        "is_demo": True,
    },
    {
        "id": SOFIA_ID,
        "display_name": "Sofía Ramírez",
        "email": "sofia.demo@fluidbank.test",
        "is_demo": True,
    },
]

ACCESSIBILITY_PREFERENCES = [
    {
        # Liquidity-crisis persona: current mock defaults preserved.
        "user_id": ANA_ID,
        "literacy_level": "medium",
        "font_scale": "lg",
        "contrast": "high",
        "color_vision_mode": "none",
        "hit_target": "large",
    },
    {
        # Subscription-review persona: comfortable, no accessibility adaptation needed.
        "user_id": LUIS_ID,
        "literacy_level": "high",
        "font_scale": "md",
        "contrast": "normal",
        "color_vision_mode": "none",
        "hit_target": "normal",
    },
    {
        # Accessible-reading-mode persona: low literacy, deuteranopia, large targets.
        "user_id": SOFIA_ID,
        "literacy_level": "low",
        "font_scale": "xl",
        "contrast": "high",
        "color_vision_mode": "deuteranopia",
        "hit_target": "large",
    },
]

ACCOUNTS = [
    {
        "id": ANA_ACCOUNT_ID,
        "user_id": ANA_ID,
        "account_type": "checking",
        "currency": "MXN",
        "available_balance": 600.00,
    },
    {
        "id": LUIS_ACCOUNT_ID,
        "user_id": LUIS_ID,
        "account_type": "checking",
        "currency": "MXN",
        "available_balance": 8500.00,
    },
    {
        "id": SOFIA_ACCOUNT_ID,
        "user_id": SOFIA_ID,
        "account_type": "savings",
        "currency": "MXN",
        "available_balance": 15000.00,
    },
]

TRANSACTIONS = [
    {
        "id": stable_id("txn:ana:rent"),
        "account_id": ANA_ACCOUNT_ID,
        "amount": 3200.00,
        "direction": "debit",
        "category": "rent",
        "merchant": "Inmobiliaria del Valle",
        "occurred_at": days_ago(2),
    },
    {
        "id": stable_id("txn:ana:groceries"),
        "account_id": ANA_ACCOUNT_ID,
        "amount": 450.00,
        "direction": "debit",
        "category": "groceries",
        "merchant": "Soriana",
        "occurred_at": days_ago(1),
    },
    {
        "id": stable_id("txn:ana:salary"),
        "account_id": ANA_ACCOUNT_ID,
        "amount": 4200.00,
        "direction": "credit",
        "category": "salary",
        "merchant": "Nómina",
        "occurred_at": days_ago(6),
    },
    {
        "id": stable_id("txn:luis:salary"),
        "account_id": LUIS_ACCOUNT_ID,
        "amount": 18000.00,
        "direction": "credit",
        "category": "salary",
        "merchant": "Nómina",
        "occurred_at": days_ago(4),
    },
    {
        "id": stable_id("txn:luis:restaurant"),
        "account_id": LUIS_ACCOUNT_ID,
        "amount": 620.00,
        "direction": "debit",
        "category": "dining",
        "merchant": "La Nacional",
        "occurred_at": days_ago(1),
    },
    {
        "id": stable_id("txn:sofia:salary"),
        "account_id": SOFIA_ACCOUNT_ID,
        "amount": 22000.00,
        "direction": "credit",
        "category": "salary",
        "merchant": "Nómina",
        "occurred_at": days_ago(5),
    },
    {
        "id": stable_id("txn:sofia:utilities"),
        "account_id": SOFIA_ACCOUNT_ID,
        "amount": 380.00,
        "direction": "debit",
        "category": "utilities",
        "merchant": "CFE",
        "occurred_at": days_ago(3),
    },
]

SUBSCRIPTIONS = [
    {
        "id": stable_id("sub:ana:renta"),
        "user_id": ANA_ID,
        "name": "Renta mensual",
        "amount": 3200.00,
        "billing_cycle": "monthly",
        "next_charge_date": (date.today() + timedelta(days=28)).isoformat(),
        "status": "active",
    },
    {
        "id": stable_id("sub:luis:streaming"),
        "user_id": LUIS_ID,
        "name": "Streaming de video",
        "amount": 199.00,
        "billing_cycle": "monthly",
        "next_charge_date": (date.today() + timedelta(days=12)).isoformat(),
        "status": "active",
    },
    {
        "id": stable_id("sub:luis:gym"),
        "user_id": LUIS_ID,
        "name": "Gimnasio",
        "amount": 450.00,
        "billing_cycle": "monthly",
        "next_charge_date": (date.today() + timedelta(days=5)).isoformat(),
        "status": "active",
    },
    {
        "id": stable_id("sub:luis:cloud"),
        "user_id": LUIS_ID,
        "name": "Almacenamiento en la nube",
        "amount": 99.00,
        "billing_cycle": "monthly",
        "next_charge_date": (date.today() + timedelta(days=20)).isoformat(),
        "status": "active",
    },
    {
        "id": stable_id("sub:sofia:streaming"),
        "user_id": SOFIA_ID,
        "name": "Streaming de música",
        "amount": 115.00,
        "billing_cycle": "monthly",
        "next_charge_date": (date.today() + timedelta(days=9)).isoformat(),
        "status": "active",
    },
]


def _client() -> Client:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def seed(client: Client) -> None:
    client.table("users").upsert(USERS, on_conflict="id").execute()
    client.table("accessibility_preferences").upsert(
        ACCESSIBILITY_PREFERENCES, on_conflict="user_id"
    ).execute()
    client.table("accounts").upsert(ACCOUNTS, on_conflict="id").execute()
    client.table("transactions").upsert(TRANSACTIONS, on_conflict="id").execute()
    client.table("subscriptions").upsert(SUBSCRIPTIONS, on_conflict="id").execute()


def main() -> None:
    client = _client()
    seed(client)
    print("Seed complete:")
    print(f"  users:                     {len(USERS)}")
    print(f"  accessibility_preferences: {len(ACCESSIBILITY_PREFERENCES)}")
    print(f"  accounts:                  {len(ACCOUNTS)}")
    print(f"  transactions:              {len(TRANSACTIONS)}")
    print(f"  subscriptions:             {len(SUBSCRIPTIONS)}")
    print("Demo user ids:")
    print(f"  ana_garcia   (crisis):      {ANA_ID}")
    print(f"  luis_torres  (subscriptions): {LUIS_ID}")
    print(f"  sofia_ramirez (projection):  {SOFIA_ID}")


if __name__ == "__main__":
    main()
