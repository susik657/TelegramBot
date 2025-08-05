import os
import time
import logging
import asyncio
from datetime import datetime, timedelta, timezone, time as dtime
import sys
import signal
import threading
import gc

from telegram import Update, Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest, Forbidden
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, TypeHandler
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from gevent.pywsgi import WSGIServer

from database import init_db, close_all_connections, get_user_language, set_user_language
from keyboard_utils import (
    create_main_menu_keyboard,
    create_plan_selection_keyboard,
    create_payment_method_keyboard,
    create_language_keyboard,
    create_back_to_menu_keyboard,
    create_payment_confirmation_keyboard,
    create_referral_keyboard,
    create_subscription_status_keyboard,
    create_admin_panel_keyboard,
    create_accounts_management_keyboard,
    create_account_action_keyboard,
    create_plan_confirmation_keyboard
)
from config import SecureConfig
from monitoring import init_monitoring
from system_health import SystemHealth, webhook_breaker
from backup_manager import BackupManager
from payment_processor import PaymentProcessor
from security_utils import (
    verify_webhook_signature,
    generate_ephemeral_wallet,
    secure_audit_log,
    secure_erase,
    SecureKeyStorage,
    validate_webhook_payload
)
from admin_panel import AdminPanel

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("secure_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

logging.getLogger('werkzeug').setLevel(logging.WARNING)
app = Flask(__name__)
load_dotenv()

SecureKeyStorage.store_key('MASTER_ENCRYPTION', os.getenv('MASTER_ENCRYPTION_KEY'))
secure_audit_log("SYSTEM", "APP_START", "Initialization")

healing_system = SystemHealth(admin_id=SecureConfig.get('ADMIN_ID'))
backup_manager = BackupManager()
payment_processor = PaymentProcessor()
admin_panel = AdminPanel(owner_id=int(SecureConfig.get('ADMIN_ID', decrypt=True)))

init_monitoring(app)

MESSAGES = {
    'ru': {
        'welcome': '🌏 <b>Добро пожаловать!</b> 🌏\nВыберите язык:\n\nРусский / English',
        'language_selected': '✅ <b>Язык установлен на русский!</b>\n\nНажмите "НАЧАТЬ" чтобы продолжить! 🚀',
        'start': '🚀 НАЧАТЬ',
        'back': '⬅️ НАЗАД',
        'menu': '🏠 МЕНЮ',
        'main_menu': '🏠 <b>ГЛАВНОЕ МЕНЮ</b>\n\nВыберите действие:',
        'check_subscription': '⏰ МОЯ ПОДПИСКА',
        'select_plan': '💳 КУПИТЬ ПОДПИСКУ',
        'purchase_details': 'ℹ️ СПОСОБЫ ОПЛАТЫ',
        'change_language': '🌐 СМЕНИТЬ ЯЗЫК',
        'channel_details': '📢 О КАНАЛЕ',
        'referral_program': '🤝 РЕФЕРАЛЬНАЯ ПРОГРАММА',
        'purchase_info': (
            '🔒 <b>СПОСОБЫ ОПЛАТЫ</b>\n\n'
            '🌐 <b>Анонимность</b>\n'
            'Для максимальной анонимности рекомендуем оплачивать через <b>USDT (TRC-20)</b>\n\n'
            '💸 <b>Комиссии</b>\n'
            'Комиссия сети TRC20 (1 USDT) оплачивается покупателем\n\n'
            '☕ <b>Без криптовалюты?</b>\n'
            'Можно оплатить через <b>Ko-fi</b> (только 1-2 месяца)\n\n'
            '⚠️ <b>Важно!</b>\n'
            'Не добавляйте комментарии при оплате через Ko-fi\n\n'
            '🛎️ <b>Доступ</b>\n'
            '• USDT: доступ сразу после оплаты\n'
            '• Ko-fi: доступ через 8 дней\n\n'
            '💰 <b>Реферальные скидки (USDT)</b>\n'
            'При покупке подписки по реферальной ссылке:\n'
            '1 месяц: <b>5%</b>\n'
            '2 месяца: <b>25%</b>\n'
            '3 месяца: <b>40%</b>\n'
            '4 месяца: <b>50%</b>\n\n'
            '🚫 <b>Важное правило!</b>\n'
            'После окончания подписки вы не сможете купить подписку повторно на наш канал.\n\n'
            '👇 <b>Выберите способ оплаты:</b>'
        ),
        'usdt': '💸 USDT (TRC-20)',
        'kofi': '☕ Ko-fi',
        'select_plan_prompt': '💰 <b>ВЫБЕРИТЕ ПЛАН ПОДПИСКИ</b>',
        'month_1': '1 МЕСЯЦ - $105',
        'month_2': '2 МЕСЯЦА - $165',
        'month_3': '3 МЕСЯЦА - $280',
        'month_4': '4 МЕСЯЦА - $450',
        'usdt_instructions': (
            '📤 <b>ОПЛАТА USDT (TRC-20)</b>\n\n'
            '📍 <b>Адрес кошелька:</b>\n'
            '<code>{address}</code>\n\n'
            '💳 <b>Сумма к оплате:</b>\n'
            '<b>{amount:.2f} USDT</b>\n\n'
            '⚠️ <b>Внимание!</b>\n'
            '1. Комиссия сети (1 USDT) оплачивается вами\n'
            '2. Отправляйте точную сумму\n'
            '3. Нажмите "ПРОВЕРИТЬ ОПЛАТУ" после перевода\n\n'
            '🔄 Проверка занимает до 5 минут'
        ),
        'payment_success': '✅ <b>Платеж подтвержден!</b>\n\nВаша подписка активирована. Приглашение в канал:\n{invite_link}',
        'payment_failed': '❌ <b>Платеж не найден.</b> Убедитесь, что вы перевели правильную сумму.',
        'payment_blocked': '🚫 <b>Доступ к оплате временно заблокирован.</b> Попробуйте позже.',
        'referral_info': (
            '🤝 <b>РЕФЕРАЛЬНАЯ ПРОГРАММА</b>\n\n'
            'Ваша ссылка: <code>{link}</code>\n'
            'Всего приглашено: {total}\n'
            'Из них активные: {active}\n'
            'Скидка на счету: ${discount}'
        ),
        'no_subscription': '❌ У вас нет активной подписки.',
        'active_subscription': '✅ <b>Ваша подписка активна до:</b> {end_date}',
        'future_access': '⏳ <b>Доступ будет предоставлен:</b> {access_date}',
        'subscription_status': '📅 <b>Статус подписки</b>\n\n{status}\n\nОсталось дней: {days_left}',
        'select_language': '🌐 <b>ВЫБЕРИТЕ ЯЗЫК</b>',
        'english': 'English',
        'russian': 'Русский',
        'kofi_confirmation': '✅ Платеж Ko-fi подтвержден! Доступ будет открыт {access_date}',
        'payment_verified': '✅ Платеж подтвержден! Доступ активирован.',
        'payment_pending': '⏳ Платеж обнаружен, ожидаем подтверждения сети...',
        'subscription_ending': '⚠️ Ваша подписка заканчивается через {days} дней',
        'channel_unavailable': '⚠️ Канал временно недоступен. Приносим извинения за неудобства.'
    },
    'en': {
        'welcome': '🌏 <b>Welcome!</b> 🌏\nChoose language:\n\nРусский / English',
        'language_selected': '✅ <b>Language set to English!</b>\n\nPress "START" to continue! 🚀',
        'start': '🚀 START',
        'back': '⬅️ BACK',
        'menu': '🏠 MENU',
        'main_menu': '🏠 <b>MAIN MENU</b>\n\nChoose action:',
        'check_subscription': '⏰ MY SUBSCRIPTION',
        'select_plan': '💳 BUY SUBSCRIPTION',
        'purchase_details': 'ℹ️ PAYMENT METHODS',
        'change_language': '🌐 CHANGE LANGUAGE',
        'channel_details': '📢 ABOUT CHANNEL',
        'referral_program': '🤝 REFERRAL PROGRAM',
        'purchase_info': (
            '🔒 <b>PAYMENT METHODS</b>\n\n'
            '🌐 <b>Anonymity</b>\n'
            'For maximum anonymity, we recommend paying via <b>USDT (TRC-20)</b>\n\n'
            '💸 <b>Fees</b>\n'
            'TRC20 network fee (1 USDT) paid by buyer\n\n'
            '☕ <b>No crypto?</b>\n'
            'You can pay via <b>Ko-fi</b> (only 1-2 months)\n\n'
            '⚠️ <b>Important!</b>\n'
            'Do NOT add comments when paying via Ko-fi\n\n'
            '🛎️ <b>Access</b>\n'
            '• USDT: immediate access\n'
            '• Ko-fi: access after 8 days\n\n'
            '💰 <b>Referral discounts (USDT)</b>\n'
            'When buying via referral link:\n'
            '1 month: <b>5%</b>\n'
            '2 months: <b>25%</b>\n'
            '3 months: <b>40%</b>\n'
            '4 months: <b>50%</b>\n\n'
            '🚫 <b>Important rule!</b>\n'
            'After subscription ends, you CANNOT purchase again.\n\n'
            '👇 <b>Choose payment method:</b>'
        ),
        'usdt': '💸 USDT (TRC-20)',
        'kofi': '☕ Ko-fi',
        'select_plan_prompt': '💰 <b>CHOOSE SUBSCRIPTION PLAN</b>',
        'month_1': '1 MONTH - $105',
        'month_2': '2 MONTHS - $165',
        'month_3': '3 MONTHS - $280',
        'month_4': '4 MONTHS - $450',
        'usdt_instructions': (
            '📤 <b>USDT (TRC-20) PAYMENT</b>\n\n'
            '📍 <b>Wallet address:</b>\n'
            '<code>{address}</code>\n\n'
            '💳 <b>Amount:</b>\n'
            '<b>{amount:.2f} USDT</b>\n\n'
            '⚠️ <b>Attention!</b>\n'
            '1. Network fee (1 USDT) paid by you\n'
            '2. Send exact amount\n'
            '3. Click "CHECK PAYMENT" after transfer\n\n'
            '🔄 Verification takes up to 5 minutes'
        ),
        'payment_success': '✅ <b>Payment confirmed!</b>\n\nYour subscription is activated. Channel invite:\n{invite_link}',
        'payment_failed': '❌ <b>Payment not found.</b> Ensure you sent correct amount.',
        'payment_blocked': '🚫 <b>Payment access temporarily blocked.</b> Try later.',
        'referral_info': (
            '🤝 <b>REFERRAL PROGRAM</b>\n\n'
            'Your link: <code>{link}</code>\n'
            'Total invited: {total}\n'
            'Active: {active}\n'
            'Discount balance: ${discount}'
        ),
        'no_subscription': '❌ You have no active subscription.',
        'active_subscription': '✅ <b>Subscription active until:</b> {end_date}',
        'future_access': '⏳ <b>Access will be granted:</b> {access_date}',
        'subscription_status': '📅 <b>SUBSCRIPTION STATUS</b>\n\n{status}\n\nDays left: {days_left}',
        'select_language': '🌐 <b>SELECT LANGUAGE</b>',
        'english': 'English',
        'russian': 'Русский',
        'kofi_confirmation': '✅ Ko-fi payment confirmed! Access will be granted on {access_date}',
        'payment_verified': '✅ Payment verified! Access activated.',
        'payment_pending': '⏳ Payment detected, waiting for network confirmation...',
        'subscription_ending': '⚠️ Your subscription ends in {days} days',
        'channel_unavailable': '⚠️ Channel is temporarily unavailable. We apologize for the inconvenience.'
    }
}


@app.before_request
def limit_remote_addr():
    return


@app.route('/webhook/kofi', methods=['POST'])
def kofi_webhook():
    if not webhook_breaker.allow_request():
        return jsonify({'status': 'service unavailable'}), 503

    data = request.json
    secret = SecureConfig.get('KOFI_WEBHOOK_TOKEN', decrypt=True)
    signature = request.headers.get('X-Kofi-Signature')

    if not verify_webhook_signature(data, signature, secret) or not validate_webhook_payload(data):
        logger.warning("Invalid Ko-fi webhook")
        webhook_breaker.record_failure()
        secure_audit_log("WEBHOOK", "KOFI_INVALID")
        return jsonify({'status': 'invalid'}), 403

    secure_audit_log("WEBHOOK", "KOFI_VALID", data.get('transaction_id'))
    # ... обработка платежа ...
    return jsonify({'status': 'success'})


@app.route('/webhook/binance', methods=['POST'])
def binance_webhook():
    if not webhook_breaker.allow_request():
        return jsonify({'status': 'service unavailable'}), 503

    data = request.json
    # Аналогичная проверка для Binance
    # ...
    return jsonify({'status': 'success'})


async def safe_edit_message(message, text, reply_markup=None, parse_mode=None):
    try:
        await message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        await message.reply_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    is_admin = admin_panel.is_admin(user_id)
    keyboard = create_main_menu_keyboard(MESSAGES, lang, is_admin)

    try:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                text=MESSAGES[lang]['main_menu'],
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                MESSAGES[lang]['main_menu'],
                reply_markup=keyboard,
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Error showing main menu: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text=MESSAGES[lang]['main_menu'],
            reply_markup=keyboard,
            parse_mode='HTML'
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    language_code = update.effective_user.language_code
    lang = 'ru' if language_code and language_code.startswith('ru') else 'en'

    set_user_language(user_id, lang)

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(MESSAGES[lang]['start'], callback_data='start')]])
    await update.message.reply_text(MESSAGES[lang]['welcome'], reply_markup=keyboard, parse_mode='HTML')


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    lang = get_user_language(user_id)

    if query.data == 'start':
        await show_main_menu(update, context)
    elif query.data == 'main_menu':
        await show_main_menu(update, context)
    elif query.data == 'select_plan':
        keyboard = create_plan_selection_keyboard(MESSAGES, lang)
        await query.edit_message_text(
            text=MESSAGES[lang]['select_plan_prompt'],
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    elif query.data == 'change_language':
        keyboard = create_language_keyboard(MESSAGES)
        await query.edit_message_text(
            text=MESSAGES[lang]['select_language'],
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    elif query.data == 'back_to_main':
        await show_main_menu(update, context)
    elif query.data == 'check_subscription':
        keyboard = create_subscription_status_keyboard(MESSAGES, lang)
        status_text = "Ваш текущий статус подписки..."
        await query.edit_message_text(
            text=status_text,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    elif query.data == 'purchase_info':
        keyboard = create_payment_method_keyboard(MESSAGES, lang)
        await query.edit_message_text(
            text=MESSAGES[lang]['purchase_info'],
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    elif query.data == 'usdt_payment':
        keyboard = create_payment_confirmation_keyboard(MESSAGES, lang)
        payment_info = MESSAGES[lang]['usdt_instructions'].format(
            address="Ваш_адрес_USDT",
            amount=105.00
        )
        await query.edit_message_text(
            text=payment_info,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    elif query.data == 'kofi_payment':
        keyboard = create_back_to_menu_keyboard(MESSAGES, lang)
        await query.edit_message_text(
            text="Инструкции по оплате через Ko-fi...",
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    elif query.data.startswith('plan_'):
        plan_id = query.data.split('_')[1]
        keyboard = create_plan_confirmation_keyboard(plan_id, lang)
        await query.edit_message_text(
            text=f"Подтвердите покупку плана {plan_id}",
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    elif query.data == 'referral_program':
        keyboard = create_referral_keyboard(MESSAGES, lang)
        referral_info = MESSAGES[lang]['referral_info'].format(
            link="https://t.me/your_bot?start=ref123",
            total=5,
            active=3,
            discount=25.50
        )
        await query.edit_message_text(
            text=referral_info,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    elif query.data == 'channel_info':
        keyboard = create_back_to_menu_keyboard(MESSAGES, lang)
        await query.edit_message_text(
            text="Информация о нашем канале...",
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    elif query.data == 'admin_panel':
        await show_admin_panel(update, context)
    elif query.data == 'manage_accounts':
        await show_accounts_management(update, context)
    elif query.data.startswith('account_'):
        account_id = int(query.data.split('_')[1])
        await show_account_actions(update, context, account_id)


async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = create_admin_panel_keyboard()
    await query.edit_message_text(
        text="<b>👑 Админ-панель</b>",
        reply_markup=keyboard,
        parse_mode='HTML'
    )


async def show_accounts_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = create_accounts_management_keyboard(admin_panel.account_manager)
    await query.edit_message_text(
        text="<b>👥 Управление аккаунтами</b>",
        reply_markup=keyboard,
        parse_mode='HTML'
    )


async def show_account_actions(update: Update, context: ContextTypes.DEFAULT_TYPE, account_id: int):
    query = update.callback_query
    await query.answer()
    account_data = admin_panel.account_manager.active_accounts.get(account_id, {})

    status = "Активен ✅" if account_data.get('is_active') else "Неактивен ❌"
    proxy = account_data.get('proxy', 'Не настроен')

    text = (
        f"<b>Аккаунт {account_id}</b>\n\n"
        f"<b>Метод аутентификации:</b> {account_data.get('auth_method', 'N/A')}\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Прокси:</b> {proxy}\n\n"
        "Выберите действие:"
    )

    keyboard = create_account_action_keyboard(account_id)
    await query.edit_message_text(
        text=text,
        reply_markup=keyboard,
        parse_mode='HTML'
    )


async def handle_payment(user_id, amount, currency, context: ContextTypes.DEFAULT_TYPE):
    if currency == 'USDT':
        wallet_address = payment_processor.generate_payment_address(user_id, amount)
        lang = get_user_language(user_id)
        message = MESSAGES[lang]['usdt_instructions'].format(
            address=wallet_address,
            amount=amount
        )
        await context.bot.send_message(user_id, message, parse_mode='HTML')
        payment_processor.monitor_payment(user_id, amount)


async def verify_usdt_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tx_id = context.args[0] if context.args else None

    if not tx_id:
        await update.message.reply_text("Please provide transaction ID")
        return

    lang = get_user_language(user_id)
    if payment_processor.verify_payment(user_id, tx_id):
        await update.message.reply_text(
            MESSAGES[lang]['payment_verified'],
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            MESSAGES[lang]['payment_failed'],
            parse_mode='HTML'
        )


async def check_subscription_end(context: ContextTypes.DEFAULT_TYPE):
    from database import get_expiring_subscriptions
    expiring_subs = get_expiring_subscriptions(7)

    for sub in expiring_subs:
        lang = get_user_language(sub['user_id'])
        days_left = (sub['end_date'] - datetime.now()).days
        if days_left in [1, 3, 7]:
            message = MESSAGES[lang]['subscription_ending'].format(days=days_left)
            await context.bot.send_message(sub['user_id'], message, parse_mode='HTML')


async def check_channel_availability(context: ContextTypes.DEFAULT_TYPE):
    channel_id = SecureConfig.get('CHANNEL_ID', decrypt=True)
    try:
        bot = context.bot
        chat = await bot.get_chat(chat_id=channel_id)
        if not chat:
            raise Exception("Channel not available")
    except Exception as e:
        healing_system.send_admin_alert(f"⚠️ Channel unavailable: {str(e)}")
        from database import get_active_subscribers
        active_users = get_active_subscribers()

        for user_id in active_users:
            lang = get_user_language(user_id)
            await context.bot.send_message(
                user_id,
                MESSAGES[lang]['channel_unavailable'],
                parse_mode='HTML'
            )


def graceful_shutdown(signum, frame):
    logger.info("Received shutdown signal, exiting...")
    secure_audit_log("SYSTEM", "APP_SHUTDOWN")
    payment_processor.shutdown()
    close_all_connections()
    SecureKeyStorage.erase_all()
    admin_panel.commenter.stop()
    gc.collect()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    init_db()

    try:
        backup_path = backup_manager.create_backup()
        if backup_path:
            logger.info(f"Initial backup created: {backup_path}")
    except Exception as e:
        logger.error(f"Backup failed: {e}")

    application = Application.builder().token(
        SecureConfig.get('TELEGRAM_TOKEN', decrypt=True)
    ).build()

    if application.job_queue:
        application.job_queue.run_repeating(
            callback=check_subscription_end,
            interval=86400,
            first=10
        )

        application.job_queue.run_repeating(
            callback=check_channel_availability,
            interval=3600,
            first=30
        )

        application.job_queue.run_daily(
            callback=cleanup_expired_subscriptions,
            time=dtime(hour=2, minute=0)
        )

        application.job_queue.run_daily(
            callback=lambda ctx: backup_manager.create_backup(),
            time=dtime(hour=3, minute=0)
        )

        application.job_queue.run_repeating(
            callback=healing_system.run_checks,
            interval=300,
            first=15
        )

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('verify_payment', verify_usdt_payment))
    application.add_handler(CallbackQueryHandler(button_callback))

    def safe_run_flask():
        try:
            logger.info("Starting secure Flask server on port 8443")
            server = WSGIServer(
                ('0.0.0.0', 8443),
                app,
                keyfile='key.pem',
                certfile='cert.pem'
            )
            server.serve_forever()
        except Exception as e:
            logger.exception("Flask server crashed")

    flask_thread = threading.Thread(target=safe_run_flask, daemon=True)
    flask_thread.start()

    try:
        application.run_polling()
    except Exception as e:
        healing_system.report_error(e)
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        graceful_shutdown(None, None)


if __name__ == '__main__':
    main()