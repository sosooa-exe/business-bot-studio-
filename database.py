from functools import lru_cache


from supabase import Client, create_client

from config import SUPABASE_URL, SUPABASE_SECRET_KEY


@lru_cache(maxsize=1)
def get_db() -> Client:
    return create_client(
        SUPABASE_URL,
        SUPABASE_SECRET_KEY
    )


def get_business_by_owner(telegram_id: int) -> dict | None:
    response = (
        get_db()
        .table("businesses")
        .select("*")
        .eq("owner_telegram_id", telegram_id)
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None

def get_business_by_slug(slug: str) -> dict | None:
    response = (
        get_db()
        .table("businesses")
        .select("*")
        .eq("slug", slug)
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None
    

def get_settings() -> dict:
    response = (
        get_db()
        .table("bot_settings")
        .select("*")
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else {}


def update_settings(data: dict) -> dict:
    settings = get_settings()

    if not settings:
        return {}

    response = (
        get_db()
        .table("bot_settings")
        .update(data)
        .eq("id", settings["id"])
        .execute()
    )
    return response.data[0] if response.data else {}


def get_active_services(business_id: str) -> list[dict]:
    response = (
        get_db()
        .table("services")
        .select("*")
        .eq("business_id", business_id)
        .eq("is_active", True)
        .order("sort_order")
        .execute()
    )
    return response.data or []
    

def create_lead(data: dict) -> dict:
    response = (
        get_db()
        .table("leads")
        .insert(data)
        .execute()
    )
    return response.data[0] if response.data else {}


def create_booking(data: dict) -> dict:
    response = (
        get_db()
        .table("bookings")
        .insert(data)
        .execute()
    )
    return response.data[0] if response.data else {}


def get_recent_leads(limit: int = 10) -> list[dict]:
    response = (
        get_db()
        .table("leads")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []


def get_recent_bookings(limit: int = 10) -> list[dict]:
    response = (
        get_db()
        .table("bookings")
        .select("*, services(title)")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []


def create_service(data: dict) -> dict:
    response = (
        get_db()
        .table("services")
        .insert(data)
        .execute()
    )
    return response.data[0] if response.data else {}


def update_service(service_id: str, data: dict) -> dict:
    response = (
        get_db()
        .table("services")
        .update(data)
        .eq("id", service_id)
        .execute()
    )
    return response.data[0] if response.data else {}


def deactivate_service(service_id: str) -> dict:
    response = (
        get_db()
        .table("services")
        .update({"is_active": False})
        .eq("id", service_id)
        .execute()
    )
    return response.data[0] if response.data else {}


def get_all_services() -> list[dict]:
    response = (
        get_db()
        .table("services")
        .select("*")
        .order("sort_order")
        .execute()
    )
    return response.data or []
