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
    update_settings,
    get_active_services,
    create_lead,
    create_booking,
    get_recent_leads,
    get_recent_bookings,
    create_service,
    update_service,
    deactivate_service,
    get_all_services,
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

class ServiceForm(StatesGroup):
    title = State()
    price = State()
    description = State()


class EditServiceForm(StatesGroup):
    service_id = State()
    title = State()
    price = State()
    description = State()


class SettingsForm(StatesGroup):
    bot_name = State()
    welcome_text = State()
    contact_phone = State()
    contact_username = State()


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
@dp.message(Command("leads"))
async def leads(message: Message):
    if not admin(message.from_user.id):
        return

    items = get_recent_leads()

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


@dp.message(Command("services"))
async def services_admin(message: Message):
    if not admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    items = get_all_services()

    if not items:
        await message.answer("Услуг пока нет.")
        return

    for item in items:
        status = "Активна" if item.get("is_active") else "Отключена"
        await message.answer(
            f"Услуга: {item.get('title')}\n"
            f"Цена: {price(item.get('price'))}\n"
            f"Описание: {item.get('description') or '—'}\n"
            f"Статус: {status}\n"
            f"ID: {item.get('id')}"
        )


@dp.message(Command("editservice"))
async def edit_service_start(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer("Укажите ID услуги. Посмотреть ID можно через /services")
        return

    service_id = parts[1].strip()
    services = get_all_services()
    service = next(
        (item for item in services if str(item.get("id")) == service_id),
        None
    )

    if not service:
        await message.answer("Услуга не найдена.")
        return

    await state.update_data(service_id=service_id)
    await state.set_state(EditServiceForm.title)
    await message.answer(
        f"Текущее название: {service.get('title')}\n"
        "Введите новое название:"
    )

@dp.message(EditServiceForm.title)
async def edit_service_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(EditServiceForm.price)
    await message.answer("Введите новую цену цифрами или «по запросу»:")

@dp.message(EditServiceForm.price)
async def edit_service_price(message: Message, state: FSMContext):
    value = message.text.strip().lower()

    if value == "по запросу":
        service_price = None
    else:
        try:
            service_price = float(value.replace(",", "."))
            if service_price < 0:
                raise ValueError
        except ValueError:
            await message.answer("Введите цену числом или «по запросу».")
            return

    await state.update_data(price=service_price)
    await state.set_state(EditServiceForm.description)
    await message.answer("Введите новое описание:")

@dp.message(EditServiceForm.description)
async def edit_service_description(message: Message, state: FSMContext):
    data = await state.get_data()

    try:
        result = update_service(
            data["service_id"],
            {
                "title": data["title"],
                "price": data["price"],
                "description": message.text.strip(),
            }
        )
        if not result:
            await message.answer("Не удалось найти или обновить услугу.")
            await state.clear()
            return
    except Exception:
        logging.exception("Ошибка редактирования услуги")
        await message.answer("Не удалось обновить услугу.")
        await state.clear()
        return

    await state.clear()
    await message.answer("Услуга успешно обновлена!")


@dp.message(Command("addservice"))
async def add_service_start(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    await state.set_state(ServiceForm.title)
    await message.answer("Введите название новой услуги:")


@dp.message(ServiceForm.title)
async def add_service_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(ServiceForm.price)
    await message.answer(
        "Введите цену цифрами или напишите «по запросу»:"
    )


@dp.message(ServiceForm.price)
async def add_service_price(message: Message, state: FSMContext):
    value = message.text.strip().lower()

    if value == "по запросу":
        service_price = None
    else:
        try:
            service_price = float(value.replace(",", "."))
            if service_price < 0:
                raise ValueError
        except ValueError:
            await message.answer(
                "Введите цену числом или напишите «по запросу»."
            )
            return

    await state.update_data(price=service_price)
    await state.set_state(ServiceForm.description)
    await message.answer("Введите описание услуги:")


@dp.message(ServiceForm.description)
async def add_service_description(message: Message, state: FSMContext):
    data = await state.get_data()

    try:
        create_service({
            "title": data["title"],
            "price": data["price"],
            "description": message.text.strip(),
            "is_active": True,
        })
    except Exception:
        logging.exception("Ошибка создания услуги")
        await message.answer(
            "Не удалось добавить услугу. Проверьте логи Railway."
        )
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"Услуга «{data['title']}» успешно добавлена!"
    )
@dp.message(Command("settings"))
async def settings_start(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    settings = get_settings()

    if not settings:
        await message.answer("Настройки не найдены.")
        return

    await message.answer(
        "⚙️ Настройки бизнеса\n\n"
        f"Название: {settings.get('bot_name')}\n"
        f"Приветствие: {settings.get('welcome_text')}\n"
        f"Телефон: {settings.get('contact_phone')}\n"
        f"Telegram: {settings.get('contact_username')}\n\n"
        "Чтобы изменить настройки, напишите:\n"
        "/editsettings"
    )

@dp.message(Command("editsettings"))
async def edit_settings_start(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    await state.set_state(SettingsForm.bot_name)
    await message.answer("Введите новое название бизнеса:")

@dp.message(SettingsForm.bot_name)
async def edit_settings_name(message: Message, state: FSMContext):
    await state.update_data(bot_name=message.text.strip())
    await state.set_state(SettingsForm.welcome_text)
    await message.answer("Введите новое приветствие:")

@dp.message(SettingsForm.welcome_text)
async def edit_settings_welcome(message: Message, state: FSMContext):
    await state.update_data(welcome_text=message.text.strip())
    await state.set_state(SettingsForm.contact_phone)
    await message.answer("Введите контактный телефон:")

@dp.message(SettingsForm.contact_phone)
async def edit_settings_phone(message: Message, state: FSMContext):
    await state.update_data(contact_phone=message.text.strip())
    await state.set_state(SettingsForm.contact_username)
    await message.answer("Введите Telegram для связи (например, @username):")

@dp.message(SettingsForm.contact_username)
async def edit_settings_username(message: Message, state: FSMContext):
    data = await state.get_data()
    data["contact_username"] = message.text.strip()

    try:
        result = update_settings(data)
        if not result:
            await message.answer("Не удалось сохранить настройки.")
            await state.clear()
            return
    except Exception:
        logging.exception("Ошибка обновления настроек")
        await message.answer("Ошибка при сохранении настроек.")
        await state.clear()
        return

    await state.clear()
    await message.answer("Настройки бизнеса успешно обновлены!")


@dp.message(Command("deleteservice"))
async def delete_service_command(message: Message):
    if not admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "Укажите ID услуги.\nПример: /deleteservice 1\n\n"
            "Посмотреть ID можно командой /services"
        )
        return

    service_id = parts[1].strip()

    try:
        result = deactivate_service(service_id)
        if not result:
            await message.answer("Услуга не найдена.")
            return
    except Exception:
        logging.exception("Ошибка отключения услуги")
        await message.answer("Не удалось отключить услугу.")
        return

    await message.answer("Услуга отключена и скрыта из каталога.")
    
async def main():
    logging.info("Business Bot Studio запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
