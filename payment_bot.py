#!/usr/bin/env python3
"""
Бот оплаты @maria_svami_bot
Запускается с сайта — сразу показывает спецусловия и ведёт к оплате курса.
"""

import asyncio
import json
import os
import logging
from datetime import datetime, timedelta

import aiohttp
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
    ContextTypes,
)

# ─── НАСТРОЙКИ ────────────────────────────────────────────────────────────────
TOKEN             = os.environ["PAYMENT_BOT_TOKEN"]
YOOKASSA_TOKEN    = os.getenv("YOOKASSA_TOKEN", "")
COURSE_CHANNEL_ID = os.getenv("COURSE_CHANNEL_ID", "")
ADMIN_CHAT_ID     = os.getenv("ADMIN_CHAT_ID", "")
SHEET_URL         = os.getenv("SHEET_URL", "")          # Google Apps Script URL

KRUZHOK_DIAG_PATH = os.path.join(os.path.dirname(__file__), "kruzhok_diagnostic.mp4")

# ─── ОТСЛЕЖИВАНИЕ ОПЛАТ ───────────────────────────────────────────────────────
paid_users: set = set()

# ─── ЛОГИРОВАНИЕ ──────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s · %(name)s · %(levelname)s · %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ─── GOOGLE SHEETS ────────────────────────────────────────────────────────────
async def log_to_sheet(event: str, **kwargs):
    """Отправляет событие в Google Sheets через Apps Script."""
    if not SHEET_URL:
        return
    try:
        params = {"event": event, **{k: str(v) for k, v in kwargs.items()}}
        async with aiohttp.ClientSession() as session:
            await session.post(
                SHEET_URL, data=params,
                timeout=aiohttp.ClientTimeout(total=6),
                allow_redirects=True,
            )
    except Exception as exc:
        logger.warning("Sheet log skipped: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
# /start — сразу спецусловия
# ══════════════════════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    await update.message.reply_text(
        "Курс «Основы управления интуицией»\n\n"
        "🔥 *Специальные условия для тебя*\n"
        "Стандартная цена курса: 6 990 ₽\n\n"
        "В ближайшие 60 минут цена курса для тебя:\n"
        "→ *3 990 ₽* \\(скидка *3 000 ₽*\\)\n\n"
        "После — стоимость вернётся к стандартной 🕐",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Приобрести курс за 3990 ₽", callback_data="buy_course"),
        ]]),
    )
    # Логируем в таблицу
    await log_to_sheet(
        "start",
        user_id=user.id,
        name=user.full_name,
        username=user.username or "",
        bot="payment",
    )
    # Таймер: если через 60 мин не оплатил — кружок
    asyncio.create_task(delayed_no_payment_reminder(
        update.get_bot(), update.message.chat_id, user.id
    ))


# ══════════════════════════════════════════════════════════════════════════════
# КНОПКА «Приобрести курс» → согласие + кнопка «Оплатить»
# ══════════════════════════════════════════════════════════════════════════════
async def buy_course_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user

    await q.message.reply_text(
        'Нажимая кнопку "Оплатить", вы соглашаетесь:\n\n'
        '☑️ Я ознакомлен(а) с <a href="https://maria-alpidovskaya.ru/oferta">публичной Офертой</a>\n\n'
        '☑️ Я ознакомлен(а) с <a href="https://maria-alpidovskaya.ru/politika-opd">Политикой обработки персональных данных</a> '
        'и с <a href="https://maria-alpidovskaya.ru/soglasie-opd">Согласием на обработку персональных данных</a>\n\n'
        '☑️ Я даю согласие на получение бесплатных гайдов, памяток, чек-листов, а также иных материалов '
        'информационного и рекламного характера, в том числе посредством sms-уведомления.',
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("💳 Оплатить", callback_data="pay_now"),
        ]]),
    )
    await log_to_sheet(
        "payment_bot_buy_click",
        user_id=user.id,
        name=user.full_name,
        username=user.username or "",
        bot="payment",
    )


# ══════════════════════════════════════════════════════════════════════════════
# КНОПКА «Оплатить» → invoice
# ══════════════════════════════════════════════════════════════════════════════
async def pay_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user

    receipt_data = json.dumps({
        "receipt": {
            "items": [
                {
                    "description": "Курс «Основы управления интуицией»",
                    "quantity": 1,
                    "amount": {"value": "3990.00", "currency": "RUB"},
                    "vat_code": 1,
                    "payment_mode": "full_payment",
                    "payment_subject": "service"
                }
            ],
            "tax_system_code": 2
        }
    }, ensure_ascii=False)

    try:
        await context.bot.send_invoice(
            chat_id=q.message.chat_id,
            title="Курс «Основы управления интуицией»",
            description="Доступ к курсу на 1 месяц",
            payload="course_intuition_3990",
            provider_token=YOOKASSA_TOKEN,
            currency="RUB",
            prices=[LabeledPrice("Курс «Основы управления интуицией»", 399000)],
            provider_data=receipt_data,
            need_name=True,
            need_email=True,
            send_email_to_provider=True,
            need_phone_number=True,
        )
        await log_to_sheet(
            "payment_bot_invoice_sent",
            user_id=user.id,
            name=user.full_name,
            username=user.username or "",
            bot="payment",
        )
    except Exception as e:
        print(f"[PAY_NOW ERROR] {type(e).__name__}: {e}", flush=True)
        logger.error("send_invoice failed: %s", e)
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text="Не удалось открыть оплату. Попробуйте ещё раз или напишите нам.",
        )


# ══════════════════════════════════════════════════════════════════════════════
# PRE-CHECKOUT + УСПЕШНАЯ ОПЛАТА
# ══════════════════════════════════════════════════════════════════════════════
async def pre_checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    paid_users.add(user.id)

    purchase_date = datetime.now().strftime("%d.%m.%Y")
    expiry_date   = (datetime.now() + timedelta(days=30)).strftime("%d.%m.%Y")

    # Ссылка на канал курса
    channel_link = "https://t.me/+VNnNxLOM3BE5NTEy"
    if COURSE_CHANNEL_ID:
        try:
            invite = await context.bot.create_chat_invite_link(
                chat_id=int(COURSE_CHANNEL_ID),
                member_limit=1,
            )
            channel_link = invite.invite_link
        except Exception as exc:
            logger.warning("Channel invite failed: %s", exc)

    await update.message.reply_text(
        f"✅ Оплата прошла успешно!\n\n"
        f"Вот твоя персональная ссылка для входа в курс:\n{channel_link}\n\n"
        f"Доступ действует до {expiry_date}. Добро пожаловать! 🎉"
    )

    # Лог в таблицу «Купили курс»
    name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "—"
    tg   = f"@{user.username}" if user.username else ""
    await log_to_sheet(
        "purchase",
        user_id=user.id,
        name=name,
        username=tg,
        purchase_date=purchase_date,
        expiry_date=expiry_date,
        amount="3990",
    )

    # Уведомляем администратора
    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(
                    "💰 *Новая оплата курса (payment bot)*\n\n"
                    f"👤 {name}\n"
                    f"📱 {tg}  |  ID: `{user.id}`\n"
                    f"💵 Сумма: 3 990 ₽\n"
                    f"📅 Доступ до: {expiry_date}"
                ),
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.warning("Admin notify failed: %s", exc)

    # Таймер продления: через 29 дней напомнить
    asyncio.create_task(delayed_renewal_reminder(
        context.bot, update.message.chat_id, user.id
    ))


# ══════════════════════════════════════════════════════════════════════════════
# НАПОМИНАНИЕ ЧЕРЕЗ 60 МИН (не оплатил) → кружок + диагностика
# ══════════════════════════════════════════════════════════════════════════════
async def delayed_no_payment_reminder(bot, chat_id: int, user_id: int):
    await asyncio.sleep(60 * 60)  # 60 минут
    if user_id in paid_users:
        return  # уже оплатил

    try:
        with open(KRUZHOK_DIAG_PATH, "rb") as f:
            await asyncio.wait_for(
                bot.send_video_note(chat_id=chat_id, video_note=f),
                timeout=60,
            )
    except Exception as exc:
        logger.warning("Diagnostic kruzhok failed: %s", exc)

    try:
        diag_url = "https://t.me/svami_assistent?text=%D0%97%D0%B4%D1%80%D0%B0%D0%B2%D1%81%D1%82%D0%B2%D1%83%D0%B9%D1%82%D0%B5%2C+%D1%85%D0%BE%D1%87%D1%83+%D0%B7%D0%B0%D0%BF%D0%B8%D1%81%D0%B0%D1%82%D1%8C%D1%81%D1%8F+%D0%BA+%D0%9C%D0%B0%D1%80%D0%B8%D0%B8+%D0%BD%D0%B0+%D0%B1%D0%B5%D1%81%D0%BF%D0%BB%D0%B0%D1%82%D0%BD%D1%83%D1%8E+%D0%B4%D0%B8%D0%B0%D0%B3%D0%BD%D0%BE%D1%81%D1%82%D0%B8%D0%BA%D1%83"
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "Я вижу, что вы ещё не успели оформить курс.\n\n"
                "Если есть сомнения или вопросы — приглашаю на бесплатную 30-минутную диагностику.\n\n"
                "Разберём, как именно вам развивать интуицию, и отвечу на любые вопросы 🙏"
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📅 Записаться на диагностику", url=diag_url),
            ]]),
        )
    except Exception as exc:
        logger.warning("No-payment reminder failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
# НАПОМИНАНИЕ ЧЕРЕЗ 29 ДНЕЙ → продление за 990 ₽
# ══════════════════════════════════════════════════════════════════════════════
async def delayed_renewal_reminder(bot, chat_id: int, user_id: int):
    await asyncio.sleep(29 * 24 * 60 * 60)  # 29 дней

    receipt_data = json.dumps({
        "receipt": {
            "items": [
                {
                    "description": "Продление доступа к курсу «Основы управления интуицией»",
                    "quantity": 1,
                    "amount": {"value": "990.00", "currency": "RUB"},
                    "vat_code": 1,
                    "payment_mode": "full_payment",
                    "payment_subject": "service"
                }
            ],
            "tax_system_code": 2
        }
    }, ensure_ascii=False)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "⏰ Завтра заканчивается доступ к курсу «Основы управления интуицией».\n\n"
                "Вы можете продлить доступ ещё на месяц за *990 ₽*.\n\n"
                "Нажмите кнопку ниже, чтобы продлить 👇"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Продлить за 990 ₽", callback_data="renew_course"),
            ]]),
        )
    except Exception as exc:
        logger.warning("Renewal reminder failed: %s", exc)


async def renew_course_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    receipt_data = json.dumps({
        "receipt": {
            "items": [
                {
                    "description": "Продление доступа к курсу «Основы управления интуицией»",
                    "quantity": 1,
                    "amount": {"value": "990.00", "currency": "RUB"},
                    "vat_code": 1,
                    "payment_mode": "full_payment",
                    "payment_subject": "service"
                }
            ],
            "tax_system_code": 2
        }
    }, ensure_ascii=False)

    try:
        await context.bot.send_invoice(
            chat_id=q.message.chat_id,
            title="Продление курса «Основы управления интуицией»",
            description="Продление доступа на 1 месяц",
            payload="course_renewal_990",
            provider_token=YOOKASSA_TOKEN,
            currency="RUB",
            prices=[LabeledPrice("Продление доступа", 99000)],
            provider_data=receipt_data,
            need_name=True,
            need_email=True,
            send_email_to_provider=True,
        )
    except Exception as e:
        print(f"[RENEW ERROR] {type(e).__name__}: {e}", flush=True)
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text="Не удалось открыть оплату. Попробуйте ещё раз или напишите нам.",
        )


# ══════════════════════════════════════════════════════════════════════════════
# ЗАПУСК
# ══════════════════════════════════════════════════════════════════════════════
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buy_course_callback,  pattern="^buy_course$"))
    app.add_handler(CallbackQueryHandler(pay_now_callback,     pattern="^pay_now$"))
    app.add_handler(CallbackQueryHandler(renew_course_callback, pattern="^renew_course$"))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    logger.info("Payment bot запущен ✓")
    app.run_polling()


if __name__ == "__main__":
    main()
