from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import logging
import traceback

logger = logging.getLogger(__name__)

def build_menu(buttons, n_cols=1, header_buttons=None, footer_buttons=None):
    try:
        menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
        if header_buttons:
            menu.insert(0, header_buttons)
        if footer_buttons:
            menu.append(footer_buttons)
        return InlineKeyboardMarkup(menu)
    except Exception as e:
        logger.error(f"Error building menu: {e}\n{traceback.format_exc()}")
        return InlineKeyboardMarkup([])

def create_inline_keyboard(button_list, n_cols=1):
    try:
        buttons = []
        for text, callback in button_list:
            buttons.append(InlineKeyboardButton(text, callback_data=callback))
        return build_menu(buttons, n_cols=n_cols)
    except Exception as e:
        logger.error(f"Error creating inline keyboard: {e}\n{traceback.format_exc()}")
        return InlineKeyboardMarkup([])

def create_main_menu_keyboard(messages, lang='ru', is_admin=False):
    try:
        buttons = [
            (messages[lang]['check_subscription'], 'check_subscription'),
            (messages[lang]['select_plan'], 'select_plan'),
            (messages[lang]['purchase_details'], 'purchase_info'),
            (messages[lang]['change_language'], 'change_language'),
            (messages[lang]['channel_details'], 'channel_info'),
            (messages[lang]['referral_program'], 'referral_program')
        ]

        if is_admin:
            buttons.append(("👑 Админ", 'admin_panel'))

        return create_inline_keyboard(buttons, n_cols=2)
    except Exception as e:
        logger.error(f"Error creating main menu keyboard: {e}\n{traceback.format_exc()}")
        return InlineKeyboardMarkup([])

def create_plan_selection_keyboard(messages, lang='ru'):
    try:
        buttons = [
            (messages[lang]['month_1'], 'plan_1'),
            (messages[lang]['month_2'], 'plan_2'),
            (messages[lang]['month_3'], 'plan_3'),
            (messages[lang]['month_4'], 'plan_4'),
            (messages[lang]['back'], 'back_to_main')
        ]
        return create_inline_keyboard(buttons, n_cols=2)
    except Exception as e:
        logger.error(f"Error creating plan selection keyboard: {e}\n{traceback.format_exc()}")
        return InlineKeyboardMarkup([])

def create_payment_method_keyboard(messages, lang='ru'):
    try:
        buttons = [
            (messages[lang]['usdt'], 'usdt_payment'),
            (messages[lang]['kofi'], 'kofi_payment'),
            (messages[lang]['back'], 'back_to_plans')
        ]
        return create_inline_keyboard(buttons, n_cols=2)
    except Exception as e:
        logger.error(f"Error creating payment method keyboard: {e}\n{traceback.format_exc()}")
        return InlineKeyboardMarkup([])

def create_language_keyboard(messages):
    try:
        buttons = [
            (messages['ru']['russian'], 'lang_ru'),
            (messages['en']['english'], 'lang_en'),
            ('⬅️ Назад', 'back_to_main')
        ]
        return create_inline_keyboard(buttons, n_cols=2)
    except Exception as e:
        logger.error(f"Error creating language keyboard: {e}\n{traceback.format_exc()}")
        return InlineKeyboardMarkup([])

def create_back_to_menu_keyboard(messages, lang='ru'):
    try:
        button = [(messages[lang]['menu'], 'main_menu')]
        return create_inline_keyboard(button, n_cols=1)
    except Exception as e:
        logger.error(f"Error creating back to menu keyboard: {e}\n{traceback.format_exc()}")
        return InlineKeyboardMarkup([])

def create_payment_confirmation_keyboard(messages, lang='ru'):
    try:
        buttons = [
            (messages[lang]['back'], 'back_to_main'),
            ("✅ Проверить оплату", 'check_payment')
        ]
        return create_inline_keyboard(buttons, n_cols=2)
    except Exception as e:
        logger.error(f"Error creating payment confirmation keyboard: {e}\n{traceback.format_exc()}")
        return InlineKeyboardMarkup([])

def create_referral_keyboard(messages, lang='ru'):
    try:
        buttons = [
            ("📤 Поделиться ссылкой", 'share_referral'),
            (messages[lang]['back'], 'back_to_main')
        ]
        return create_inline_keyboard(buttons, n_cols=1)
    except Exception as e:
        logger.error(f"Error creating referral keyboard: {e}\n{traceback.format_exc()}")
        return InlineKeyboardMarkup([])

def create_subscription_status_keyboard(messages, lang='ru'):
    try:
        buttons = [
            (messages[lang]['back'], 'back_to_main'),
            ("🔄 Обновить", 'refresh_subscription')
        ]
        return create_inline_keyboard(buttons, n_cols=2)
    except Exception as e:
        logger.error(f"Error creating subscription status keyboard: {e}\n{traceback.format_exc()}")
        return InlineKeyboardMarkup([])

def create_admin_panel_keyboard():
    buttons = [
        ("👥 Управление аккаунтами", 'manage_accounts'),
        ("💬 Авто-комментирование", 'auto_commenting'),
        ("⚙️ Настройки прокси", 'proxy_settings'),
        ("📊 Статус работы", 'work_status'),
        ("🏠 Главное меню", 'main_menu')
    ]
    return create_inline_keyboard(buttons, n_cols=1)

def create_accounts_management_keyboard(account_manager):
    buttons = []
    for account_id, data in account_manager.active_accounts.items():
        status = "✅" if data['is_active'] else "❌"
        buttons.append((f"{status} Аккаунт {account_id}", f"account_{account_id}"))

    buttons.append(("➕ Добавить аккаунт", 'add_account'))
    buttons.append(("🏠 На главную", 'admin_panel'))
    return create_inline_keyboard(buttons, n_cols=2)

def create_back_to_admin_keyboard():
    button = [("⬅️ Назад", 'admin_panel')]
    return create_inline_keyboard(button, n_cols=1)

def create_account_action_keyboard(account_id):
    buttons = [
        ("🔄 Включить/выключить", f'toggle_account_{account_id}'),
        ("✏️ Изменить прокси", f'edit_proxy_{account_id}'),
        ("🗑️ Удалить", f'delete_account_{account_id}'),
        ("⬅️ Назад", 'manage_accounts')
    ]
    return create_inline_keyboard(buttons, n_cols=2)

def create_comment_templates_keyboard():
    buttons = [
        ("📝 Текстовые", 'text_templates'),
        ("🖼️ Медиа", 'media_templates'),
        ("📝+🖼️ Комбинированные", 'combined_templates'),
        ("🗑️ Удалить шаблон", 'delete_template'),
        ("🏠 На главную", 'admin_panel')
    ]
    return create_inline_keyboard(buttons, n_cols=2)

def create_template_actions_keyboard(template_id):
    buttons = [
        ("✏️ Редактировать", f'edit_template_{template_id}'),
        ("🗑️ Удалить", f'delete_template_{template_id}'),
        ("⬅️ Назад", 'comment_templates')
    ]
    return create_inline_keyboard(buttons, n_cols=2)

def create_plan_confirmation_keyboard(plan_id, lang='ru'):
    prices = {
        '1': 105,
        '2': 165,
        '3': 280,
        '4': 450
    }
    price = prices.get(plan_id, '?')
    button_text = f"Подтвердить покупку ({price}$)"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(button_text, callback_data=f"confirm_plan_{plan_id}")
    ]])