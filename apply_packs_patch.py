"""
Патч: наборы (packs) + новое сообщение о нехватке алмазов.

Что делает:
1. database.py   — таблицы packs / pack_videos / pack_claims + функции работы с ними.
2. keyboards.py  — клавиатуры входа в магазин (алмазы/наборы), список наборов,
                   кнопка "Выполнить задание", клавиатуры для админского добавления
                   видео (выбор типа + выбор набора).
3. handlers/user.py  — новое сообщение при нехватке алмазов (с кнопкой на TikTok-задание).
4. handlers/earn.py  — текст задания TikTok вынесен в функцию + новый callback
                   "open_tiktok_task" (кнопка ведёт сразу на задание).
5. handlers/shop.py  — магазин теперь спрашивает "Алмазы 💎 / Наборы 📦",
                   логика выдачи набора (только после TikTok-задания, только 1 раз,
                   не привязано к токену бота — всё по user_id в общей базе).
6. handlers/admin.py — "➕ Добавить видео" теперь сначала спрашивает,
                   что добавляем: видео для просмотра или видео в набор.

Бэкапы каждого файла создаются рядом с суффиксом .bak_packs перед правкой.
Скрипт идемпотентен: если патч уже применён — просто сообщит об этом и ничего не сломает.
"""

import re
import shutil
import sys

FILES = ["database.py", "keyboards.py", "handlers/user.py", "handlers/earn.py",
         "handlers/shop.py", "handlers/admin.py"]


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def backup(path):
    bak = path.replace("/", "_") + ".bak_packs"
    shutil.copyfile(path, bak)
    print(f"  backup -> {bak}")


def replace_once(content, old, new, label):
    count = content.count(old)
    if count == 0:
        raise SystemExit(f"❌ Anchor not found: {label}")
    if count > 1:
        raise SystemExit(f"❌ Anchor matched {count} times (expected 1): {label}")
    return content.replace(old, new, 1)


ALREADY_APPLIED_MARK = "# --- Наборы (паки) ---"


def patch_database():
    path = "database.py"
    content = read(path)
    if ALREADY_APPLIED_MARK in content:
        print(f"  {path}: уже пропатчен, пропускаю")
        return
    backup(path)

    old_tables = '''        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER,
                sender TEXT,
                admin_id INTEGER,
                text TEXT,
                sent_at TEXT
            )
        """)
        await db.commit()

        for package in SHOP_PACKAGES:'''
    new_tables = '''        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER,
                sender TEXT,
                admin_id INTEGER,
                text TEXT,
                sent_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS packs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pack_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pack_id INTEGER,
                file_id TEXT,
                file_path TEXT,
                added_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pack_claims (
                user_id INTEGER,
                pack_id INTEGER,
                claimed_at TEXT,
                PRIMARY KEY (user_id, pack_id)
            )
        """)
        await db.commit()

        for package in SHOP_PACKAGES:'''
    content = replace_once(content, old_tables, new_tables, "database.py: table creation block")

    old_seed_end = '''            if row is None:
                price = DEFAULT_SHOP_PRICES.get(package, 0)
                await db.execute(
                    "INSERT INTO shop_prices (package, price_usdt) VALUES (?, ?)",
                    (package, price)
                )
        await db.commit()


async def add_user'''
    new_seed_end = '''            if row is None:
                price = DEFAULT_SHOP_PRICES.get(package, 0)
                await db.execute(
                    "INSERT INTO shop_prices (package, price_usdt) VALUES (?, ?)",
                    (package, price)
                )
        await db.commit()

        cur = await db.execute("SELECT COUNT(*) FROM packs")
        packs_count = (await cur.fetchone())[0]
        if packs_count == 0:
            await db.execute(
                "INSERT INTO packs (name, created_at) VALUES (?, ?)",
                ("Набор 1", datetime.utcnow().isoformat())
            )
            await db.commit()


async def add_user'''
    content = replace_once(content, old_seed_end, new_seed_end, "database.py: default pack seeding")

    new_functions = '''

# --- Наборы (паки) ---

async def _ensure_pack_tables(db):
    await db.execute("""
        CREATE TABLE IF NOT EXISTS packs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            created_at TEXT
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS pack_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pack_id INTEGER,
            file_id TEXT,
            file_path TEXT,
            added_at TEXT
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS pack_claims (
            user_id INTEGER,
            pack_id INTEGER,
            claimed_at TEXT,
            PRIMARY KEY (user_id, pack_id)
        )
    """)
    await db.commit()


async def get_all_packs() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_pack_tables(db)
        cur = await db.execute("SELECT id, name FROM packs ORDER BY id")
        return await cur.fetchall()


async def get_pack(pack_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_pack_tables(db)
        cur = await db.execute("SELECT id, name FROM packs WHERE id = ?", (pack_id,))
        return await cur.fetchone()


async def get_available_packs_for_user(user_id: int) -> list:
    """Паки, которые пользователь ещё не забирал (уже полученные — скрыты)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_pack_tables(db)
        cur = await db.execute("""
            SELECT p.id, p.name FROM packs p
            WHERE p.id NOT IN (
                SELECT pack_id FROM pack_claims WHERE user_id = ?
            )
            ORDER BY p.id
        """, (user_id,))
        return await cur.fetchall()


async def add_pack_video(pack_id: int, file_id: str, file_path: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_pack_tables(db)
        await db.execute(
            "INSERT INTO pack_videos (pack_id, file_id, file_path, added_at) VALUES (?, ?, ?, ?)",
            (pack_id, file_id, file_path, datetime.utcnow().isoformat())
        )
        await db.commit()


async def get_pack_videos(pack_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_pack_tables(db)
        cur = await db.execute(
            "SELECT file_id, file_path FROM pack_videos WHERE pack_id = ? ORDER BY id",
            (pack_id,)
        )
        return await cur.fetchall()


async def is_pack_claimed(user_id: int, pack_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_pack_tables(db)
        cur = await db.execute(
            "SELECT 1 FROM pack_claims WHERE user_id = ? AND pack_id = ?",
            (user_id, pack_id)
        )
        return (await cur.fetchone()) is not None


async def claim_pack(user_id: int, pack_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_pack_tables(db)
        await db.execute(
            "INSERT OR IGNORE INTO pack_claims (user_id, pack_id, claimed_at) VALUES (?, ?, ?)",
            (user_id, pack_id, datetime.utcnow().isoformat())
        )
        await db.commit()


async def has_user_completed_tiktok(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM tiktok_submissions WHERE user_id = ? AND status = 'approved' LIMIT 1",
            (user_id,)
        )
        return (await cur.fetchone()) is not None
'''
    content = content.rstrip("\n") + "\n" + new_functions
    write(path, content)
    print(f"  {path}: OK")


def patch_keyboards():
    path = "keyboards.py"
    content = read(path)
    if "def shop_entry_kb" in content:
        print(f"  {path}: уже пропатчен, пропускаю")
        return
    backup(path)

    new_functions = '''

def shop_entry_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💎 Алмазы", callback_data="shop_diamonds"),
            InlineKeyboardButton(text="📦 Наборы", callback_data="shop_packs"),
        ],
    ])


def packs_list_kb(packs: list) -> InlineKeyboardMarkup:
    rows = []
    for pack in packs:
        rows.append([InlineKeyboardButton(
            text=f"📦 {pack['name']}",
            callback_data=f"openpack:{pack['id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tiktok_cta_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Выполнить задание", callback_data="open_tiktok_task")]
    ])


def add_video_type_kb() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🎬 Видео для просмотра")],
        [KeyboardButton(text="📦 Видео в набор")],
        [KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def add_video_pack_choice_kb(packs: list) -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text=f"📦 {p['name']}")] for p in packs]
    buttons.append([KeyboardButton(text="⬅️ Назад")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
'''
    content = content.rstrip("\n") + "\n" + new_functions
    write(path, content)
    print(f"  {path}: OK")


def patch_user():
    path = "handlers/user.py"
    content = read(path)
    if "tiktok_cta_kb" in content:
        print(f"  {path}: уже пропатчен, пропускаю")
        return
    backup(path)

    content = replace_once(
        content,
        "from keyboards import next_video_kb",
        "from keyboards import next_video_kb, tiktok_cta_kb",
        "user.py: import"
    )

    old_block = '''    if user["balance"] < WATCH_COST:
        await send_text_func(
            f"❌ <b>Недостаточно алмазов</b> 💎 для просмотра видео.\\n"
            f"Нужно: <b>{WATCH_COST}</b> 💎, у вас: <b>{user['balance']}</b> 💎"
        )
        return'''
    new_block = '''    if user["balance"] < WATCH_COST:
        await send_text_func(
            "😔 <b>Недостаточно алмазов</b> для просмотра видео.\\n\\n"
            "Не беда! Можно пополнить баланс, выполнив задание TikTok 😀",
            reply_markup=tiktok_cta_kb()
        )
        return'''
    content = replace_once(content, old_block, new_block, "user.py: insufficient balance message")

    write(path, content)
    print(f"  {path}: OK")


def patch_earn():
    path = "handlers/earn.py"
    content = read(path)
    if "_tiktok_task_text" in content:
        print(f"  {path}: уже пропатчен, пропускаю")
        return
    backup(path)

    content = replace_once(
        content,
        "from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton",
        "from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton",
        "earn.py: import CallbackQuery"
    )

    old_handler = '''@router.message(StateFilter(None), F.text == "🎵 Задание TikTok")
async def earn_tiktok(message: Message):
    await message.answer(
        "🎵 <b>Задание — TikTok</b>\\n"
        "🎁 Награда: <b>20 💎</b>\\n\\n"
        "<b>1️⃣ Шаг первый.</b> Зайди в TikTok, в поиске введи:\\n"
        "<code>det pit</code>\\n\\n"
        "<b>2️⃣ Шаг второй.</b> Сделай <b>10 комментариев</b>, чередуя тексты ниже "
        "(нажми на текст — он скопируется):\\n\\n"
        "<blockquote><code>DarkArhangel.duckdns.org лучшее ❤️</code>\\n"
        "<code>DarkArhangel.duckdns.org the best 😻</code>\\n"
        "<code>DarkArhangel.duckdns.org сдесь 👑</code>\\n"
        "<code>DarkArhangel.duckdns.org фри 🆓</code></blockquote>\\n\\n"
        f"<b>3️⃣ Шаг третий.</b> Сделай <b>{TIKTOK_SCREENSHOTS_REQUIRED} скриншотов</b> "
        "с этими комментариями и нажми кнопку ниже, чтобы отправить их на модерацию.",
        reply_markup=tiktok_task_kb()
    )'''
    new_handler = '''def _tiktok_task_text() -> str:
    return (
        "🎵 <b>Задание — TikTok</b>\\n"
        "🎁 Награда: <b>20 💎</b>\\n\\n"
        "<b>1️⃣ Шаг первый.</b> Зайди в TikTok, в поиске введи:\\n"
        "<code>det pit</code>\\n\\n"
        "<b>2️⃣ Шаг второй.</b> Сделай <b>10 комментариев</b>, чередуя тексты ниже "
        "(нажми на текст — он скопируется):\\n\\n"
        "<blockquote><code>DarkArhangel.duckdns.org лучшее ❤️</code>\\n"
        "<code>DarkArhangel.duckdns.org the best 😻</code>\\n"
        "<code>DarkArhangel.duckdns.org сдесь 👑</code>\\n"
        "<code>DarkArhangel.duckdns.org фри 🆓</code></blockquote>\\n\\n"
        f"<b>3️⃣ Шаг третий.</b> Сделай <b>{TIKTOK_SCREENSHOTS_REQUIRED} скриншотов</b> "
        "с этими комментариями и нажми кнопку ниже, чтобы отправить их на модерацию."
    )


@router.message(StateFilter(None), F.text == "🎵 Задание TikTok")
async def earn_tiktok(message: Message):
    await message.answer(_tiktok_task_text(), reply_markup=tiktok_task_kb())


@router.callback_query(F.data == "open_tiktok_task")
async def open_tiktok_task_cb(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(_tiktok_task_text(), reply_markup=tiktok_task_kb())'''
    content = replace_once(content, old_handler, new_handler, "earn.py: tiktok task handler")

    write(path, content)
    print(f"  {path}: OK")


def patch_shop():
    path = "handlers/shop.py"
    content = read(path)
    if "shop_entry_kb" in content:
        print(f"  {path}: уже пропатчен, пропускаю")
        return
    backup(path)

    content = replace_once(
        content,
        '''from database import (
    get_shop_prices, get_shop_price, add_invoice, get_invoice,
    mark_invoice_paid, update_balance, delete_invoice, get_setting,
    get_shop_price_rub, add_yoomoney_invoice,
)
from keyboards import shop_packages_kb, invoice_kb, payment_method_kb, yoomoney_invoice_kb''',
        '''from database import (
    get_shop_prices, get_shop_price, add_invoice, get_invoice,
    mark_invoice_paid, update_balance, delete_invoice, get_setting,
    get_shop_price_rub, add_yoomoney_invoice,
    get_available_packs_for_user, is_pack_claimed, has_user_completed_tiktok,
    get_pack_videos, claim_pack, get_pack,
)
from keyboards import (
    shop_packages_kb, invoice_kb, payment_method_kb, yoomoney_invoice_kb,
    shop_entry_kb, packs_list_kb, tiktok_cta_kb,
)''',
        "shop.py: imports"
    )

    old_shop = '''@router.message(F.text == "🛍 Магазин")
async def open_shop(message: Message):
    prices = await get_shop_prices()
    text = "🛍 <b>Магазин алмазов</b> 💎\\n\\n<i>Выберите пакет:</i>"
    kb = shop_packages_kb(prices)

    photo_path = await get_setting("shop_photo")
    if photo_path and os.path.exists(photo_path):
        await message.answer_photo(FSInputFile(photo_path), caption=text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("pkg:"))
async def choose_package(callback: CallbackQuery):'''
    new_shop = '''@router.message(F.text == "🛍 Магазин")
async def open_shop(message: Message):
    text = "🛍 <b>Магазин</b>\\n\\n<i>Что хотите приобрести?</i>"
    kb = shop_entry_kb()

    photo_path = await get_setting("shop_photo")
    if photo_path and os.path.exists(photo_path):
        await message.answer_photo(FSInputFile(photo_path), caption=text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "shop_diamonds")
async def shop_diamonds(callback: CallbackQuery):
    prices = await get_shop_prices()
    await callback.answer()
    await callback.message.answer(
        "💎 <b>Магазин алмазов</b>\\n\\n<i>Выберите пакет:</i>",
        reply_markup=shop_packages_kb(prices)
    )


@router.callback_query(F.data == "shop_packs")
async def shop_packs(callback: CallbackQuery):
    packs = await get_available_packs_for_user(callback.from_user.id)
    await callback.answer()
    if not packs:
        await callback.message.answer("📦 <i>Наборов пока нет.</i>")
        return
    await callback.message.answer(
        "📦 <b>Наборы</b>\\n\\n<i>Выберите набор:</i>",
        reply_markup=packs_list_kb(packs)
    )


@router.callback_query(F.data.startswith("openpack:"))
async def open_pack(callback: CallbackQuery):
    pack_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    if await is_pack_claimed(user_id, pack_id):
        await callback.answer("Недоступно", show_alert=True)
        packs = await get_available_packs_for_user(user_id)
        try:
            if packs:
                await callback.message.edit_reply_markup(reply_markup=packs_list_kb(packs))
            else:
                await callback.message.edit_text("📦 <i>Наборов пока нет.</i>")
        except Exception:
            pass
        return

    if not await has_user_completed_tiktok(user_id):
        await callback.answer()
        await callback.message.answer(
            "🔒 <b>Этот набор выдаётся только после выполнения задания TikTok</b>\\n"
            "Забрать его можно только <b>один раз</b> — сразу после первого "
            "выполнения задания, и никогда больше.",
            reply_markup=tiktok_cta_kb()
        )
        return

    videos = await get_pack_videos(pack_id)
    if not videos:
        await callback.answer()
        await callback.message.answer("📦 <i>В этом наборе пока нет видео — загляните позже.</i>")
        return

    await claim_pack(user_id, pack_id)
    pack = await get_pack(pack_id)
    await callback.answer()
    pack_name = pack["name"] if pack else "Набор"
    await callback.message.answer(f"🎉 <b>Забирай набор «{pack_name}»!</b>")

    for v in videos:
        file_id = v["file_id"]
        file_path = v["file_path"]
        video_input = file_id if file_id else (FSInputFile(file_path) if file_path else None)
        if video_input:
            try:
                await callback.message.answer_video(video_input)
            except Exception:
                pass


@router.callback_query(F.data.startswith("pkg:"))
async def choose_package(callback: CallbackQuery):'''
    content = replace_once(content, old_shop, new_shop, "shop.py: shop entry + packs logic")

    write(path, content)
    print(f"  {path}: OK")


def patch_admin():
    path = "handlers/admin.py"
    content = read(path)
    if "AddVideoStates.choosing_type" in content:
        print(f"  {path}: уже пропатчен, пропускаю")
        return
    backup(path)

    content = replace_once(
        content,
        '''from database import (
    get_users_count, get_videos_count, add_video,
    get_setting, set_setting, delete_setting,
    get_shop_prices, set_shop_price,
    get_earn_tokens_count, get_all_earn_tokens,
    get_pending_tiktok_submissions, get_tiktok_submission,
    set_tiktok_submission_status, update_balance,
    clear_tiktok_screenshots, get_users_page, get_all_user_ids,
)''',
        '''from database import (
    get_users_count, get_videos_count, add_video,
    get_setting, set_setting, delete_setting,
    get_shop_prices, set_shop_price,
    get_earn_tokens_count, get_all_earn_tokens,
    get_pending_tiktok_submissions, get_tiktok_submission,
    set_tiktok_submission_status, update_balance,
    clear_tiktok_screenshots, get_users_page, get_all_user_ids,
    get_all_packs, add_pack_video,
)''',
        "admin.py: database imports"
    )

    content = replace_once(
        content,
        '''from keyboards import (
    main_menu_kb, admin_menu_kb, save_videos_kb, greeting_menu_kb, admin_shop_prices_kb,
    admin_tiktok_list_kb, tiktok_moderation_kb, admin_stats_kb, users_list_kb,
    broadcast_confirm_kb, support_reply_cancel_kb,
)''',
        '''from keyboards import (
    main_menu_kb, admin_menu_kb, save_videos_kb, greeting_menu_kb, admin_shop_prices_kb,
    admin_tiktok_list_kb, tiktok_moderation_kb, admin_stats_kb, users_list_kb,
    broadcast_confirm_kb, support_reply_cancel_kb,
    add_video_type_kb, add_video_pack_choice_kb,
)''',
        "admin.py: keyboards imports"
    )

    content = replace_once(
        content,
        '''class AddVideoStates(StatesGroup):
    waiting_videos = State()''',
        '''class AddVideoStates(StatesGroup):
    choosing_type = State()
    waiting_videos = State()
    choosing_pack = State()
    waiting_pack_videos = State()''',
        "admin.py: AddVideoStates"
    )

    old_start = '''@router.message(F.text == "➕ Добавить видео")
async def start_add_video(message: Message, state: FSMContext):
    if not _is_admin(message):
        return
    await state.set_state(AddVideoStates.waiting_videos)
    await state.update_data(count=0)
    await message.answer(
        "📤 <i>Отправляйте видео по одному, я буду принимать каждое.</i>\\n"
        "Когда закончите — нажмите «💾 Сохранить».",
        reply_markup=save_videos_kb()
    )'''
    new_start = '''@router.message(F.text == "➕ Добавить видео")
async def start_add_video(message: Message, state: FSMContext):
    if not _is_admin(message):
        return
    await state.set_state(AddVideoStates.choosing_type)
    await message.answer(
        "Что добавляем?",
        reply_markup=add_video_type_kb()
    )


@router.message(AddVideoStates.choosing_type, F.text == "🎬 Видео для просмотра")
async def add_video_choose_watch(message: Message, state: FSMContext):
    if not _is_admin(message):
        return
    await state.set_state(AddVideoStates.waiting_videos)
    await state.update_data(count=0)
    await message.answer(
        "📤 <i>Отправляйте видео по одному, я буду принимать каждое.</i>\\n"
        "Когда закончите — нажмите «💾 Сохранить».",
        reply_markup=save_videos_kb()
    )


@router.message(AddVideoStates.choosing_type, F.text == "📦 Видео в набор")
async def add_video_choose_pack_type(message: Message, state: FSMContext):
    if not _is_admin(message):
        return
    packs = await get_all_packs()
    if not packs:
        await state.clear()
        await message.answer("📦 Наборов ещё нет.", reply_markup=admin_menu_kb())
        return
    await state.set_state(AddVideoStates.choosing_pack)
    await state.update_data(packs={p["name"]: p["id"] for p in packs})
    await message.answer("Выберите набор:", reply_markup=add_video_pack_choice_kb(packs))


@router.message(AddVideoStates.choosing_type)
async def add_video_choosing_type_wrong(message: Message):
    if not _is_admin(message):
        return
    await message.answer("Выберите вариант кнопкой снизу.")


@router.message(AddVideoStates.choosing_pack)
async def add_video_pack_chosen(message: Message, state: FSMContext):
    if not _is_admin(message):
        return
    data = await state.get_data()
    packs_map = data.get("packs", {})
    name = (message.text or "").replace("📦 ", "", 1)
    pack_id = packs_map.get(name)
    if pack_id is None:
        await message.answer("Выберите набор кнопкой снизу.")
        return
    await state.update_data(pack_id=pack_id, count=0)
    await state.set_state(AddVideoStates.waiting_pack_videos)
    await message.answer(
        f"📤 <i>Отправляйте видео для набора «{name}» по одному.</i>\\n"
        "Когда закончите — нажмите «💾 Сохранить».",
        reply_markup=save_videos_kb()
    )


@router.message(AddVideoStates.waiting_pack_videos, F.video)
async def receive_pack_video(message: Message, state: FSMContext, bot: Bot):
    if not _is_admin(message):
        return

    data = await state.get_data()
    pack_id = data.get("pack_id")

    video = message.video
    file_size_mb = round(video.file_size / (1024 * 1024), 2)

    file_path = None
    try:
        destination = os.path.join(VIDEOS_DIR, f"pack_{video.file_id}.mp4")
        await bot.download(video.file_id, destination=destination)
        file_path = destination
    except Exception:
        file_path = None

    await add_pack_video(pack_id, video.file_id, file_path)

    new_count = data.get("count", 0) + 1
    await state.update_data(count=new_count)

    note = "" if file_path else "\\n⚠️ <i>Файл больше 20 МБ — сохранён без локальной копии на VPS.</i>"
    await message.answer(
        f"✅ Видео принято в набор (размер {file_size_mb} МБ){note}\\n"
        f"Добавлено в этой сессии: <b>{new_count}</b>"
    )


@router.message(AddVideoStates.waiting_pack_videos, F.text == "💾 Сохранить")
async def save_pack_videos(message: Message, state: FSMContext):
    if not _is_admin(message):
        return
    data = await state.get_data()
    count = data.get("count", 0)
    await state.clear()
    await message.answer(
        f"💾 Сохранено. Добавлено видео в набор: <b>{count}</b>",
        reply_markup=main_menu_kb(is_admin=True)
    )


@router.message(AddVideoStates.waiting_pack_videos)
async def wrong_content_pack(message: Message):
    if not _is_admin(message):
        return
    await message.answer("Пришлите видео файлом или нажмите «💾 Сохранить» для завершения.")'''
    content = replace_once(content, old_start, new_start, "admin.py: add-video flow")

    write(path, content)
    print(f"  {path}: OK")


def main():
    print("Применяю патч 'наборы' ...")
    patch_database()
    patch_keyboards()
    patch_user()
    patch_earn()
    patch_shop()
    patch_admin()
    print("\n✅ Патч применён. Дальше:")
    print("   pm2 restart videobot")
    print("   pm2 logs videobot --lines 50")


if __name__ == "__main__":
    main()
