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
TOKEN             = os.environ["PAYMENT_BOT_TOKEN"]        # токен @maria_svami_bot из BotFather
YOOKASSA_TOKEN    = os.getenv("YOOKASSA_TOKEN", "")        # тот же токен ЮКассы
COURSE_CHANNEL_ID = os.getenv("COURSE_CHANNEL_ID", "")    # ID канала курса
ADMIN_CHAT_ID     = os.getenv("ADMIN_CHAT_ID", "")

# Путь к кружку-диагностике (рядом с файлом бота)
KRUZHOK_DIAG_PATH = os.path.join(os.path.dirname(__file__), "kruzhok_diagnostic.mp4")

# ─── ОТСЛЕЖИВАНИЕ ОПЛАТ ───────────────────────────────────────────────────────
paid_users: set = set()

# ─── ЛОГИРОВАНИЕ ──────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s · %(name)s · %(levelname)s · %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# /start — приветствие
# ══════════════════════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Чтобы получить спецусловия для курса «Основы управления интуицией» — нажмите кнопку ниже 👇",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎁 Получить спецусловия", callback_data="spec_offer"),
        ]]),
    )


# ══════════════════════════════════════════════════════════════════════════════
# СПЕЦУСЛОВИЯ
# ══════════════════════════════════════════════════════════════════════════════
async def spec_offer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.reply_text(
        "🔥 *Специальные условия для тебя*\n"
        "Стандартная цена курса: 6 990 ₽\n\n"
        "В ближайшие 60 минут цена курса для тебя:\n"
        "→ 3 990 ₽ \\(скидка 3 000 ₽\\)\n\n"
        "После — стоимость вернётся к стандартной 🕐",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Приобрести курс за 3990 ₽", callback_data="buy_course"),
        ]]),
    )
    # Запускаем таймер: если не оплатит за 60 мин — напоминание с диагностикой
    asyncio.create_task(delayed_no_payment_reminder(
        context.bot, q.message.chat_id, q.from_user.id
    ))


# ══════════════════════════════════════════════════════════════════════════════
# КНОПКА «Приобрести курс» → согласие + кнопка «Оплатить»
# ══════════════════════════════════════════════════════════════════════════════
async def buy_course_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
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


# ══════════════════════════════════════════════════════════════════════════════
# КНОПКА «Оплатить» → invoice
# ══════════════════════════════════════════════════════════════════════════════
async def pay_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    receipt_data = json.dumps({
        "receipt": {
            "items": [
                {
                    "description": "Курс «Основы управления интуицией»",
                    "quantity": 1,
                    "amount": {
                        "value": "3990.00",
                        "currency": "RUB"
                    },
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

    # Уведомляем администратора
    if ADMIN_CHAT_ID:
        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "—"
        tg   = f"@{user.username}" if user.username else ""
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


# ══════════════════════════════════════════════════════════════════════════════
# НАПОМИНАНИЕ ЧЕРЕЗ 60 МИН (не оплатил) → кружок + диагностика
# ══════════════════════════════════════════════════════════════════════════════
async def delayed_no_payment_reminder(bot, chat_id: int, user_id: int):
    await asyncio.sleep(60 * 60)  # 60 минут
    if user_id in paid_users:
        return  # уже оплатил

    # Кружок
    try:
        with open(KRUZHOK_DIAG_PATH, "rb") as f:
            await bot.send_video_note(chat_id=chat_id, video_note=f)
    except Exception as exc:
        logger.warning("Diagnostic kruzhok failed: %s", exc)

    # Сообщение с предложением диагностики
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "Я вижу, что вы ещё не успели оформить курс.\n\n"
                "Если есть сомнения или вопросы — приглашаю на бесплатную 30-минутную диагностику.\n\n"
                "Разберём, как именно вам развивать интуицию, и отвечу на любые вопросы.\n\n"
                "Пишите *диагностика* в ответ — и я запишу вас 🙏"
            ),
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.warning("No-payment reminder failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
# ЗАПУСК
# ══════════════════════════════════════════════════════════════════════════════
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(spec_offer_callback,  pattern="^spec_offer$"))
    app.add_handler(CallbackQueryHandler(buy_course_callback,  pattern="^buy_course$"))
    app.add_handler(CallbackQueryHandler(pay_now_callback,     pattern="^pay_now$"))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    logger.info("Payment bot запущен ✓")
    app.run_polling()


if __name__ == "__main__":
    main()
