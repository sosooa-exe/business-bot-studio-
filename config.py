import os
from dotenv import load_dotenv

load_dotenv()


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Не задана переменная {name}")
    return value


BOT_TOKEN = required("BOT_TOKEN")
SUPABASE_URL = required("SUPABASE_URL")
SUPABASE_SECRET_KEY = required("SUPABASE_SECRET_KEY")

ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}

BUSINESS_CONTACT_TEXT = os.getenv(
    "BUSINESS_CONTACT_TEXT",
    "Напишите администратору, чтобы уточнить детали."
)
