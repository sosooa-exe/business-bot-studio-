import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, ADMIN_IDS, BUSINESS_CONTACT_TEXT
from database import (
    get_settings,
    get_active_services,
    create_lead,
    create_booking,
    get_recent_leads,
    get_recent_bookings,
)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class Booking(StatesGroup):
    name = State()
    phone = State()
    date = State()
    comment = State()


class Lead(StatesGroup):
    name = State()
    phone = State()
    message = State()


def keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🛍 Каталог"),
                KeyboardButton(text="📅 Записаться"),
            ],
            [
                KeyboardButton(text="✉️ Оставить заявку"),
                KeyboardButton(text="☎️ Контакты"),
            ],
        ],
        resize_keyboard=True,
    )


def admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def price(value):
    if value is None or value == "":
        return "Цена по запросу"
    try:
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except (ValueError, TypeError):
        return str(value)


async def notify_admins(text):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logging.exception("Ошибка отправки уведомления")


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    settings = get_settings()
    name = settings.get("bot_name") or "Наш бизнес"
    welcome = settings.get("welcome_text") or "Здравствуйте! Чем можем помочь?"

    await message.answer(
        f"<b>{name}</b>\n\n{welcome}",
        reply_markup=keyboard(),
        parse_mode="HTML",
    )


@dp.message(F.text == "🛍 Каталог")
@dp.message(Command("catalog"))
async def catalog(message: Message):
    services = get_active_services()

    if not services:
        await message.answer("Каталог пока пуст.")
        return

    for service in services:
        builder = InlineKeyboardBuilder()
        builder.button(
            text="📅 Записаться",
            callback_data=f"book:{service['id']}",
        )

        await message.answer(
            f"<b>{service.get('title', 'Услуга')}</b>\n"
            f"{service.get('description') or 'Описание уточняйте у администратора.'}\n\n"
            f"Стоимость: {price(service.get('price'))}",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )


@dp.message(F.text == "📅 Записаться")
async def booking_menu(message: Message):
    services = get_active_services()

    if not services:
        await message.answer("Пока нет доступных услуг.")
        return

    builder = InlineKeyboardBuilder()

    for service in services:
        builder.button(
            text=service.get("title", "Услуга"),
            callback_data=f"book:{service['id']}",
        )

    builder.adjust(1)
    await message.answer("Выберите услугу:", reply_markup=builder.as_markup())


@dp.callback_query(F.data.startswith("book:"))
async def choose_service(callback: CallbackQuery, state: FSMContext):
    service_id = callback.data.split(":", 1)[1]
    services = get_active_services()

    service = next(
        (s for s in services if str(s["id"]) == service_id),
        None,
    )

    if not service:
        await callback.answer("Услуга недоступна.", show_alert=True)
        return

    await state.update_data(
        service_id=service_id,
        service_title=service.get("title", "Услуга"),
    )

    await state.set_state(Booking.name)
    await callback.message.answer("Как вас зовут?")
    await callback.answer()


@dp.message(Booking.name)
async def booking_name(message: Message, state: FSMContext):
    await state.update_data(customer_name=message.text.strip())
    await state.set_state(Booking.phone)

    await message.answer(
        "Напишите номер телефона или отправьте контакт.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[
                KeyboardButton(
                    text="📱 Отправить телефон",
                    request_contact=True,
                )
            ]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


@dp.message(Booking.phone)
async def booking_phone(message: Message, state: FSMContext):
    phone = (
        message.contact.phone_number
        if message.contact
        else (message.text or "").strip()
    )

    if not phone:
        await message.answer("Пожалуйста, отправьте номер телефона.")
        return

    await state.update_data(phone=phone)
    await state.set_state(Booking.date)

    await message.answer(
        "Введите желаемую дату и время в формате:\n"
        "2026-12-05 14:30",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(Booking.date)
async def booking_date(message: Message, state: FSMContext):
    try:
        requested_at = datetime.strptime(
            message.text.strip(),
            "%Y-%m-%d %H:%M",
        ).isoformat()
    except ValueError:
        await message.answer(
            "Неверный формат. Пример: 2026-12-05 14:30"
        )
        return

    await state.update_data(requested_at=requested_at)
    await state.set_state(Booking.comment)

    await message.answer("Комментарий к записи? Если нет, напишите «Нет».")


@dp.message(Booking.comment)
async def booking_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    user = message.from_user

    comment = (
        ""
        if message.text.strip().lower() == "нет"
        else message.text.strip()
    )

    try:
        create_booking({
            "telegram_user_id": user.id,
            "telegram_username": user.username,
            "customer_name": data["customer_name"],
            "phone": data["phone"],
            "service_id": data["service_id"],
            "requested_at": data["requested_at"],
            "comment": comment,
            "status": "new",
        })
    except Exception:
        logging.exception("Ошибка сохранения записи")
        await message.answer("Не удалось сохранить запись. Попробуйте позже.")
        await state.clear()
        return

    await notify_admins(
        "🆕 <b>Новая запись!</b>\n"
        f"Услуга: {data['service_title']}\n"
        f"Имя: {data['customer_name']}\n"
        f"Телефон: {data['phone']}\n"
        f"Дата: {data['requested_at']}\n"
        f"Комментарий: {comment or '—'}\n"
        f"Telegram ID: {user.id}"
    )

    await state.clear()
    await message.answer(
        "Заявка на запись отправлена администратору!",
        reply_markup=keyboard(),
    )


@dp.message(F.text == "✉️ Оставить заявку")
async def lead_start(message: Message, state: FSMContext):
    await state.set_state(Lead.name)
    await message.answer("Как вас зовут?")


@dp.message(Lead.name)
async def lead_name(message: Message, state: FSMContext):
    await state.update_data(full_name=message.text.strip())
    await state.set_state(Lead.phone)
    await message.answer("Напишите номер телефона.")


@dp.message(Lead.phone)
async def lead_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text.strip())
    await state.set_state(Lead.message)
    await message.answer("Что вас интересует?")


@dp.message(Lead.message)
async def lead_message(message: Message, state: FSMContext):
    data = await state.get_data()
    user = message.from_user

    try:
        create_lead({
            "telegram_user_id": user.id,
            "telegram_username": user.username,
            "full_name": data["full_name"],
            "phone": data["phone"],
            "message": message.text.strip(),
            "status": "new",
        })
    except Exception:
        logging.exception("Ошибка сохранения заявки")
        await message.answer("Не удалось отправить заявку.")
        await state.clear()
        return

    await notify_admins(
        "✉️ <b>Новая заявка!</b>\n"
        f"Имя: {data['full_name']}\n"
        f"Телефон: {data['phone']}\n"
        f"Сообщение: {message.text}\n"
        f"Telegram ID: {user.id}"
    )

    await state.clear()
    await message.answer(
        "Заявка отправлена! Администратор скоро свяжется с вами.",
        reply_markup=keyboard(),
    )


@dp.message(F.text == "☎️ Контакты")
async def contacts(message: Message):
    settings = get_settings()

    phone = settings.get("contact_phone") or "Не указан"
    username = settings.get("contact_username") or "Не указан"

    await message.answer(
        f"☎️ Контакты\n"
        f"Телефон: {phone}\n"
        f"Telegram: {username}\n\n"
        f"{BUSINESS_CONTACT_TEXT}"
    )


@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    await message.answer(
        "⚙️ Панель администратора\n\n"
        "/leads — заявки\n"
        "/bookings — записи"
    )


@dp.message(Command("services"))
async def admin_services(message: Message):
    if not admin(message.from_user.id):
        return

    services = get_all_services()

    if not services:
        await message.answer("Услуг пока нет.")
        return

    text = "📋 Управление услугами:\n\n"
    for service in services:
        status = "✅" if service["is_active"] else "❌"
        text += (
            f"{status} {service['title']}\n"
            f"Цена: {service.get('price', 0)} ₽\n"
            f"ID: {service['id']}\n\n"
        )

    text += "Для добавления услуги используй /addservice"
    await message.answer(text)@dp.message(Command("leads"))
async def leads(message: Message):
    if not admin(message.from_user.id):
        return

    items = get_recent_leads()
    @dp.message(Command("addservice"))
async def add_service_start(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return

    await state.set_state(ServiceForm.title)
    await message.answer("Введите название новой услуги:")

@dp.message(ServiceForm.title)
async def add_service_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(ServiceForm.description)
    await message.answer("Введите описание услуги:")

@dp.message(ServiceForm.description)
async def add_service_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(ServiceForm.price)
    await message.answer("Введите цену услуги числом:")

@dp.message(ServiceForm.price)
async def add_service_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price < 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректную цену числом, например 1500.")
        return

    await state.update_data(price=price)
    await state.set_state(ServiceForm.duration)
    await message.answer("Введите длительность услуги в минутах:")

@dp.message(ServiceForm.duration)
async def add_service_duration(message: Message, state: FSMContext):
    try:
        duration = int(message.text)
        if duration < 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите целое число минут, например 60.")
        return

    data = await state.get_data()
    create_service({
        "title": data["title"],
        "description": data["description"],
        "price": data["price"],
        "duration_minutes": duration,
        "is_active": True,
    })

    await state.clear()
    await message.answer("✅ Новая услуга добавлена!")

    @dp.message(Command("editservice"))
async def edit_service_start(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return

    await state.set_state(ServiceEdit.service_id)
    await message.answer(
        "Введите ID услуги. Посмотреть ID можно командой /services"
    )


@dp.message(ServiceEdit.service_id)
async def edit_service_id(message: Message, state: FSMContext):
    await state.update_data(service_id=message.text.strip())
    await state.set_state(ServiceEdit.field)
    await message.answer(
        "Что изменить? Напишите:\n"
        "title — название\n"
        "price — цену\n"
        "description — описание"
    )


@dp.message(ServiceEdit.field)
async def edit_service_field(message: Message, state: FSMContext):
    field = message.text.strip().lower()

    if field not in ("title", "price", "description"):
        await message.answer("Введите title, price или description.")
        return

    await state.update_data(field=field)
    await state.set_state(ServiceEdit.value)
    await message.answer("Введите новое значение:")


@dp.message(ServiceEdit.value)
async def edit_service_value(message: Message, state: FSMContext):
    await message.answer("Не удалось обновить услугу. Проверьте ID.")
    data = await state.get_data()
    field = data["field"]
    value = message.text.strip()

    if field == "price":
        try:
            value = float(value.replace(",", "."))
            if value < 0:
                raise ValueError
        except ValueError:
            await message.answer("Введите корректную цену числом.")
            return

    result = update_service(data["service_id"], {field: value})
    await state.clear()

    if result:
        await message.answer("✅ Услуга обновлена!")
    else:
        await message.answer("Не удалось обновить услугу. Проверьте ID.")
        @dp.message(Command("deleteservice"))
async def delete_service_start(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return

    await state.set_state(ServiceDelete.service_id)
    await message.answer(
        "Введите ID услуги, которую хотите отключить.\n"
        "Посмотреть ID можно командой /services"
    )


@dp.message(ServiceDelete.service_id)
async def delete_service_confirm(message: Message, state: FSMContext):
    service_id = message.text.strip()

    result = deactivate_service(service_id)

    await state.clear()

    if result:
        await message.answer("✅ Услуга отключена и скрыта из каталога.")
    else:
        await message.answer("Не удалось отключить услугу. Проверьте ID.")

    if not items:
        await message.answer("Заявок пока нет.")
        return

    for item in items:
        await message.answer(
            f"Заявка\n"
            f"Имя: {item.get('full_name')}\n"
            f"Телефон: {item.get('phone')}\n"
            f"Сообщение: {item.get('message')}\n"
            f"Статус: {item.get('status')}"
        )


@dp.message(Command("bookings"))
async def bookings(message: Message):
    if not admin(message.from_user.id):
        return

    items = get_recent_bookings()

    if not items:
        await message.answer("Записей пока нет.")
        return

    for item in items:
        service = item.get("services") or {}

        await message.answer(
            f"Запись\n"
            f"Услуга: {service.get('title', '—')}\n"
            f"Клиент: {item.get('customer_name')}\n"
            f"Телефон: {item.get('phone')}\n"
            f"Дата: {item.get('requested_at')}\n"
            f"Статус: {item.get('status')}"
        )


async def main():
    logging.info("Business Bot Studio запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
