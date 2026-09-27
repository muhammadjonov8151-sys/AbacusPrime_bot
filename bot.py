"""
AbacusPrime Bot v2 — PostgreSQL asosida
Force-subscribe + o'quvchilar ro'yxati (viloyat/ustoz bo'yicha) + natija/reyting tizimi.

O'rnatish:
    pip install python-telegram-bot==21.6 asyncpg --break-system-packages

Muhit o'zgaruvchilari (Railway "Variables" bo'limida):
    BOT_TOKEN     — @BotFather'dan olingan token
    OWNER_ID      — sizning Telegram ID'ingiz
    DATABASE_URL  — Railway PostgreSQL avtomatik beradi (Postgres xizmatini
                    qo'shganingizda, shu o'zgaruvchini ushbu botga ham
                    "Variable Reference" orqali ulang)
"""

import asyncio
import logging
import os
import re
import random
import string

import asyncpg
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ SOZLAMALAR ============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or 0)
DATABASE_URL = os.environ.get("DATABASE_URL", "")

DEFAULT_MESSAGE = (
    "Hurmatli {mention}!\n\n"
    "Guruhda yozish uchun avval quyidagi kanal(lar)ga qo'shiling, "
    "so'ng \"✅ Tekshirish\" tugmasini bosing!"
)

# ============ DOIMIY KANALLAR RO'YXATI ============
# Bot ishga tushganda avtomatik bazaga yoziladi (agar hali yo'q bo'lsa).
DEFAULT_GROUP_ID = -1003939400499  # AbacusPrime guruhi
DEFAULT_CHANNELS = [
    {"id": -1003986384293, "name": "AbacusPrime"},
    {"id": -1004349040226, "name": "Haramayn_store"},
    {"id": -1003936814449, "name": "Haramayn_Vaqf"},
]

INSTAGRAM_LINKS = [
    {"name": "Haramayn.store", "url": "https://instagram.com/haramayn.store"},
    {"name": "AbacusPrime_", "url": "https://instagram.com/abacusprime_"},
]

AGE_CATEGORIES = ["5-6 yosh", "7-8 yosh", "9-10 yosh", "11+ yosh"]

# ============ GLOBAL DB POOL ============
db_pool: asyncpg.Pool = None


# ============================================================
#                    BAZA — SXEMA VA YORDAMCHI
# ============================================================

async def init_db(app):
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                group_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                name TEXT NOT NULL,
                invite_link TEXT NOT NULL,
                PRIMARY KEY (group_id, channel_id)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_settings (
                group_id BIGINT PRIMARY KEY,
                message TEXT NOT NULL DEFAULT ''
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS students (
                code TEXT PRIMARY KEY,
                group_id BIGINT NOT NULL,
                region TEXT NOT NULL,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                age INT NOT NULL,
                teacher_id BIGINT,
                teacher_name TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS results (
                id SERIAL PRIMARY KEY,
                code TEXT NOT NULL REFERENCES students(code) ON DELETE CASCADE,
                stage INT NOT NULL,
                score INT NOT NULL,
                entered_by BIGINT,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE (code, stage)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS verified_users (
                user_id BIGINT PRIMARY KEY,
                verified_at TIMESTAMP DEFAULT NOW()
            );
        """)

    logger.info("Baza sxemasi tayyor.")

    # Standart kanallarni bazaga yozib qo'yamiz (agar hali yo'q bo'lsa)
    if DEFAULT_GROUP_ID and DEFAULT_CHANNELS:
        async with db_pool.acquire() as conn:
            for ch in DEFAULT_CHANNELS:
                exists = await conn.fetchval(
                    "SELECT 1 FROM channels WHERE group_id=$1 AND channel_id=$2",
                    DEFAULT_GROUP_ID, ch["id"],
                )
                if exists:
                    continue
                try:
                    chat = await app.bot.get_chat(ch["id"])
                    invite_link = chat.invite_link or await app.bot.export_chat_invite_link(ch["id"])
                except Exception as e:
                    logger.warning(f"Standart kanal yuklanmadi ({ch['id']}): {e}")
                    continue
                await conn.execute(
                    "INSERT INTO channels (group_id, channel_id, name, invite_link) "
                    "VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                    DEFAULT_GROUP_ID, ch["id"], ch["name"], invite_link,
                )
        logger.info("Standart kanallar tekshirildi/tiklandi.")

    try:
        await app.bot.set_my_commands([
            BotCommand("start", "Botni ishga tushirish / yordam"),
            BotCommand("royhat", "(reply) Ro'yxat qo'shish — /royhat Viloyat"),
            BotCommand("royhatlarim", "O'zim qo'shgan o'quvchilarni ko'rish"),
            BotCommand("natijam", "Farzandimning natijasini ko'rish"),
            BotCommand("reyting", "Reytingni ko'rish — /reyting 7-8"),
            BotCommand("id", "Joriy chat ID'sini ko'rish"),
        ])
    except Exception as e:
        logger.warning(f"Buyruqlar menyusi sozlanmadi: {e}")


def age_category(age: int) -> str:
    if age <= 6:
        return "5-6 yosh"
    elif age <= 8:
        return "7-8 yosh"
    elif age <= 10:
        return "9-10 yosh"
    else:
        return "11+ yosh"


def parse_roster_line(line: str):
    line = line.strip()
    if not line:
        return None
    line = re.sub(r'^\s*\d+[\.\)]\s*', '', line)
    numbers = list(re.finditer(r'\d{1,2}', line))
    if not numbers:
        return None
    age_match = numbers[-1]
    age = int(age_match.group())
    if age < 3 or age > 20:
        return None
    name_part = line[:age_match.start()] + line[age_match.end():]
    name_part = re.sub(r'\b(yosh|yoshda|yoshi)\b', '', name_part, flags=re.IGNORECASE)
    name_part = re.sub(r'[-,;:.]+', ' ', name_part)
    name_part = re.sub(r'\s+', ' ', name_part).strip(' -,')
    if not name_part:
        return None
    return name_part, age


def region_code(region: str) -> str:
    letters = re.sub(r'[^A-Za-z]', '', region.upper())
    return (letters[:3] or "REG")


async def generate_code(conn, region: str) -> str:
    """AP-BUX-00123 kabi kod. Bir xil kod chiqib qolmasligi uchun tekshirib boradi."""
    prefix = f"AP-{region_code(region)}-"
    for _ in range(20):
        suffix = ''.join(random.choices(string.digits, k=5))
        code = prefix + suffix
        exists = await conn.fetchval("SELECT 1 FROM students WHERE code=$1", code)
        if not exists:
            return code
    # Juda kam ehtimol, lekin zaxira variant
    return prefix + ''.join(random.choices(string.digits + string.ascii_uppercase, k=6))


# ============================================================
#                    RUXSATLAR
# ============================================================

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user.id == OWNER_ID:
        return True
    if update.effective_chat.type == "private":
        return False
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def roster_target_chat_id(update: Update) -> int:
    return DEFAULT_GROUP_ID if DEFAULT_GROUP_ID else update.effective_chat.id


# ============================================================
#                    KANALLAR (FORCE-SUBSCRIBE)
# ============================================================

async def cmd_addchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
    if len(context.args) < 2:
        return await update.message.reply_text(
            "Foydalanish: /addchannel <kanal_id> <tugma_nomi>"
        )
    channel_id_str = context.args[0]
    button_name = " ".join(context.args[1:])
    try:
        channel_id = int(channel_id_str)
    except ValueError:
        return await update.message.reply_text("Kanal ID raqam bo'lishi kerak.")

    try:
        chat = await context.bot.get_chat(channel_id)
        invite_link = chat.invite_link or await context.bot.export_chat_invite_link(channel_id)
    except Exception as e:
        return await update.message.reply_text(f"Xatolik: bot shu kanalda admin emas.\n{e}")

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO channels (group_id, channel_id, name, invite_link) VALUES ($1,$2,$3,$4) "
            "ON CONFLICT (group_id, channel_id) DO UPDATE SET name=$3, invite_link=$4",
            update.effective_chat.id, channel_id, button_name, invite_link,
        )
    await update.message.reply_text(f"✅ Qo'shildi: \"{button_name}\" ({channel_id})")


async def cmd_removechannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
    if not context.args:
        return await update.message.reply_text("Foydalanish: /removechannel <kanal_id>")
    try:
        channel_id = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("Kanal ID raqam bo'lishi kerak.")

    async with db_pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM channels WHERE group_id=$1 AND channel_id=$2",
            update.effective_chat.id, channel_id,
        )
    if result.endswith("0"):
        await update.message.reply_text("Bunday kanal topilmadi.")
    else:
        await update.message.reply_text("✅ O'chirildi.")


async def cmd_listchannels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT channel_id, name FROM channels WHERE group_id=$1", update.effective_chat.id
        )
    if not rows:
        return await update.message.reply_text("Hozircha kanal qo'shilmagan.")
    lines = [f"• {r['name']} — {r['channel_id']}" for r in rows]
    await update.message.reply_text("Talab qilinadigan kanallar:\n" + "\n".join(lines))


async def cmd_setmessage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        return await update.message.reply_text(
            "Avval xabar matnini yuboring, so'ng o'sha xabarga reply qilib /setmessage yozing.\n"
            "{mention} — foydalanuvchi ismini avtomatik qo'yadi."
        )
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO group_settings (group_id, message) VALUES ($1,$2) "
            "ON CONFLICT (group_id) DO UPDATE SET message=$2",
            update.effective_chat.id, update.message.reply_to_message.text,
        )
    await update.message.reply_text("✅ Xabar matni saqlandi.")


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID: `{update.effective_chat.id}`", parse_mode="Markdown")


async def get_missing_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int, group_id: int) -> list:
    async with db_pool.acquire() as conn:
        channels = await conn.fetch(
            "SELECT channel_id, name, invite_link FROM channels WHERE group_id=$1", group_id
        )
    missing = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch["channel_id"], user_id)
            if member.status in ("left", "kicked"):
                missing.append(ch)
        except Exception:
            missing.append(ch)
    return missing


def build_keyboard(missing: list, target_user_id: int) -> InlineKeyboardMarkup:
    buttons = []
    for ch in missing:
        buttons.append([InlineKeyboardButton(f"📢 {ch['name']}", url=ch["invite_link"])])
    for ig in INSTAGRAM_LINKS:
        buttons.append([InlineKeyboardButton(f"📸 {ig['name']}", url=ig["url"])])
    buttons.append([InlineKeyboardButton("✅ Tekshirish", callback_data=f"check:{target_user_id}")])
    return InlineKeyboardMarkup(buttons)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    if update.message.sender_chat:
        return  # Kanaldan avtomatik kelgan post

    user = update.effective_user
    if user.is_bot:
        return

    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, user.id)
        if member.status in ("administrator", "creator"):
            return
    except Exception:
        pass

    missing = await get_missing_channels(context, user.id, update.effective_chat.id)
    if not missing:
        return

    try:
        await update.message.delete()
    except Exception:
        pass
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, user.id,
            permissions=ChatPermissions(can_send_messages=False),
        )
    except Exception:
        pass

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT message FROM group_settings WHERE group_id=$1", update.effective_chat.id
        )
    msg_template = row["message"] if row and row["message"] else DEFAULT_MESSAGE

    mention = user.mention_html()
    text = msg_template.replace("{mention}", mention)
    keyboard = build_keyboard(missing, user.id)

    try:
        await context.bot.send_message(user.id, text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        warn = await context.bot.send_message(
            update.effective_chat.id,
            text + "\n\n<i>(Botga shaxsiy /start bossangiz, keyingi safar bu xabar faqat sizga yuboriladi)</i>",
            reply_markup=keyboard, parse_mode="HTML",
        )

        async def _auto_delete():
            await asyncio.sleep(300)
            try:
                await context.bot.delete_message(warn.chat_id, warn.message_id)
            except Exception:
                pass

        asyncio.create_task(_auto_delete())


async def on_check_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    try:
        target_id = int(query.data.split(":", 1)[1])
    except (IndexError, ValueError):
        target_id = user.id

    if user.id != target_id:
        await query.answer("Bu tugma sizga tegishli emas!", show_alert=True)
        return

    is_group = query.message.chat.type in ("group", "supergroup")

    if is_group:
        group_chat_id = query.message.chat_id
        missing = await get_missing_channels(context, user.id, group_chat_id)
        if missing:
            await query.answer("Hali barcha kanallarga qo'shilmadingiz!", show_alert=True)
            await query.edit_message_reply_markup(reply_markup=build_keyboard(missing, user.id))
            return
        try:
            await context.bot.restrict_chat_member(
                group_chat_id, user.id,
                permissions=ChatPermissions(
                    can_send_messages=True, can_send_photos=True,
                    can_send_videos=True, can_send_other_messages=True,
                ),
            )
        except Exception:
            pass
        await query.answer("Tabriklaymiz! Endi guruhda yozishingiz mumkin.", show_alert=True)
        try:
            await query.message.delete()
        except Exception:
            pass
    else:
        # DM orqali kelgan — barcha bog'liq guruhlarda tekshirib chiqamiz
        async with db_pool.acquire() as conn:
            group_ids = await conn.fetch("SELECT DISTINCT group_id FROM channels")
        any_unmuted = False
        for row in group_ids:
            gid = row["group_id"]
            missing = await get_missing_channels(context, user.id, gid)
            if not missing:
                try:
                    await context.bot.restrict_chat_member(
                        gid, user.id,
                        permissions=ChatPermissions(
                            can_send_messages=True, can_send_photos=True,
                            can_send_videos=True, can_send_other_messages=True,
                        ),
                    )
                    any_unmuted = True
                except Exception:
                    pass
        await query.answer("Tabriklaymiz! Endi guruhda yozishingiz mumkin.", show_alert=True)
        try:
            await query.message.delete()
        except Exception:
            pass


async def on_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.delete()
    except Exception:
        pass


# ============================================================
#                    INSTAGRAM QO'LDA TASDIQLASH
# ============================================================

async def on_instagram_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == OWNER_ID:
        return
    caption = f"📸 Instagram tasdiqlash so'rovi\n\nKimdan: {user.mention_html()} (ID: {user.id})"
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"igok:{user.id}"),
        InlineKeyboardButton("❌ Rad etish", callback_data=f"igno:{user.id}"),
    ]])
    await context.bot.send_photo(
        OWNER_ID, photo=update.message.photo[-1].file_id,
        caption=caption, parse_mode="HTML", reply_markup=buttons,
    )
    await update.message.reply_text("Skrinshotingiz adminга yuborildi, tez orada tekshiriladi. ⏳")


async def on_instagram_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != OWNER_ID:
        return await query.answer("Bu tugma faqat admin uchun!", show_alert=True)

    action, target_id_str = query.data.split(":", 1)
    target_id = int(target_id_str)

    if action == "igok":
        if DEFAULT_GROUP_ID:
            try:
                await context.bot.restrict_chat_member(
                    DEFAULT_GROUP_ID, target_id,
                    permissions=ChatPermissions(
                        can_send_messages=True, can_send_photos=True,
                        can_send_videos=True, can_send_other_messages=True,
                    ),
                )
            except Exception:
                pass
        try:
            await context.bot.send_message(target_id, "✅ Instagram tasdiqlandi! Endi guruhda yozishingiz mumkin.")
        except Exception:
            pass
        await query.answer("Tasdiqlandi!")
        await query.edit_message_caption(caption=query.message.caption + "\n\n✅ TASDIQLANDI")
    else:
        try:
            await context.bot.send_message(
                target_id, "❌ Instagram skrinshoti tasdiqlanmadi. Qayta urinib ko'ring."
            )
        except Exception:
            pass
        await query.answer("Rad etildi.")
        await query.edit_message_caption(caption=query.message.caption + "\n\n❌ RAD ETILDI")


# ============================================================
#                    O'QUVCHILAR RO'YXATI
# ============================================================

async def cmd_royhat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "Viloyat nomini ko'rsating. Masalan:\n"
            "Ro'yxat xabariga reply qilib: /royhat Buxoro"
        )
    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        return await update.message.reply_text(
            "Avval o'quvchilar ro'yxatini (har qatorda: Ism Familiya - yosh) yuboring, "
            "so'ng o'sha xabarga reply qilib /royhat <viloyat> deb yozing."
        )

    region = " ".join(context.args).strip()
    teacher = update.effective_user
    group_id = roster_target_chat_id(update)
    lines = update.message.reply_to_message.text.split("\n")

    added = 0
    failed_lines = []
    codes_preview = []

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            for line in lines:
                parsed = parse_roster_line(line)
                if not parsed:
                    if line.strip():
                        failed_lines.append(line.strip())
                    continue
                name, age = parsed
                cat = age_category(age)
                code = await generate_code(conn, region)
                await conn.execute(
                    "INSERT INTO students (code, group_id, region, category, name, age, teacher_id, teacher_name) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                    code, group_id, region, cat, name, age, teacher.id, teacher.full_name,
                )
                added += 1
                if len(codes_preview) < 5:
                    codes_preview.append(f"{code} — {name}")

        counts = await conn.fetch(
            "SELECT category, COUNT(*) AS c FROM students WHERE group_id=$1 AND region=$2 GROUP BY category",
            group_id, region,
        )

    counts_map = {r["category"]: r["c"] for r in counts}
    summary = [f"✅ {region} — {added} ta o'quvchi qo'shildi.\n"]
    for cat in AGE_CATEGORIES:
        summary.append(f"• {cat}: {counts_map.get(cat, 0)} nafar")
    summary.append(f"\n{region} bo'yicha jami: {sum(counts_map.values())} nafar")

    if codes_preview:
        summary.append("\nMisol kodlar:\n" + "\n".join(codes_preview))

    if failed_lines:
        summary.append(f"\n⚠️ {len(failed_lines)} ta qator tushunilmadi:")
        for fl in failed_lines[:10]:
            summary.append(f"— {fl}")

    await update.message.reply_text("\n".join(summary))


async def cmd_royhatlarim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teacher = update.effective_user
    group_id = roster_target_chat_id(update)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT code, name, age, category, region FROM students "
            "WHERE group_id=$1 AND teacher_id=$2 ORDER BY region, category, name",
            group_id, teacher.id,
        )

    if not rows:
        return await update.message.reply_text(
            "Siz hali hech qanday o'quvchi qo'shmagansiz.\n\n"
            "Ro'yxatni yuboring, so'ng reply qilib: /royhat <viloyat>"
        )

    lines = [f"📋 {teacher.full_name} — sizning o'quvchilaringiz:\n"]
    current_region = None
    for r in rows:
        if r["region"] != current_region:
            current_region = r["region"]
            lines.append(f"\n{current_region}:")
        lines.append(f"  • {r['code']} — {r['name']} ({r['age']} yosh, {r['category']})")
    lines.append(f"\n\nJami: {len(rows)} nafar")
    await update.message.reply_text("\n".join(lines))


async def cmd_royhatdanchiqar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
    if not context.args:
        return await update.message.reply_text(
            "'Ism Familiya - yosh' xabariga reply qilib: /royhatdanchiqar Buxoro"
        )
    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        return await update.message.reply_text(
            "O'chirmoqchi bo'lgan o'quvchi ismi va yoshini alohida xabar qilib yuboring, "
            "so'ng o'sha xabarga reply qilib /royhatdanchiqar <viloyat> deb yozing."
        )

    region = " ".join(context.args).strip()
    parsed = parse_roster_line(update.message.reply_to_message.text.split("\n")[0])
    if not parsed:
        return await update.message.reply_text("Ism va yoshni tushuna olmadim. Format: Ism Familiya - yosh")

    target_name, target_age = parsed
    group_id = roster_target_chat_id(update)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT code FROM students WHERE group_id=$1 AND region=$2 "
            "AND LOWER(name)=LOWER($3) AND age=$4 LIMIT 1",
            group_id, region, target_name, target_age,
        )
        if not row:
            return await update.message.reply_text(
                f"❌ {target_name} ({target_age} yosh) {region} ro'yxatida topilmadi."
            )
        await conn.execute("DELETE FROM students WHERE code=$1", row["code"])

    await update.message.reply_text(
        f"✅ {target_name} ({target_age} yosh) {region} ro'yxatidan olib tashlandi. (Kod: {row['code']})"
    )


async def cmd_royhatlar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = roster_target_chat_id(update)
    only_region = " ".join(context.args).strip() if context.args else None

    async with db_pool.acquire() as conn:
        if only_region:
            rows = await conn.fetch(
                "SELECT code, name, age, category, region FROM students "
                "WHERE group_id=$1 AND LOWER(region)=LOWER($2) ORDER BY category, name",
                group_id, only_region,
            )
        else:
            rows = await conn.fetch(
                "SELECT code, name, age, category, region FROM students "
                "WHERE group_id=$1 ORDER BY region, category, name",
                group_id,
            )

    if not rows:
        return await update.message.reply_text("Hozircha ro'yxat yo'q.")

    lines = ["ABACUSPRIME — ISHTIROKCHILAR RO'YXATI\n"]
    current_region = None
    region_count = 0
    grand_total = 0
    for r in rows:
        if r["region"] != current_region:
            if current_region is not None:
                lines.append(f"\n({current_region} jami: {region_count})")
            current_region = r["region"]
            region_count = 0
            lines.append(f"\n\n########## {current_region.upper()} ##########")
        lines.append(f"{r['code']} — {r['name']} — {r['age']} yosh — {r['category']}")
        region_count += 1
        grand_total += 1
    lines.append(f"\n({current_region} jami: {region_count})")
    lines.append(f"\n\nUMUMIY JAMI: {grand_total} nafar")

    file_path = f"/tmp/royhat_{group_id}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    await update.message.reply_document(
        document=open(file_path, "rb"), filename="royhat.txt",
        caption=f"Jami: {grand_total} nafar o'quvchi.",
    )


async def cmd_royhattozala(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
    group_id = roster_target_chat_id(update)

    async with db_pool.acquire() as conn:
        if context.args:
            region = " ".join(context.args).strip()
            result = await conn.execute(
                "DELETE FROM students WHERE group_id=$1 AND LOWER(region)=LOWER($2)",
                group_id, region,
            )
            await update.message.reply_text(f"✅ {region} ro'yxati tozalandi.")
        else:
            await conn.execute("DELETE FROM students WHERE group_id=$1", group_id)
            await update.message.reply_text("✅ Barcha viloyatlar ro'yxati tozalandi.")


async def cmd_ustozlar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat admin uchun.")
    group_id = roster_target_chat_id(update)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT teacher_id, teacher_name, region, COUNT(*) AS c "
            "FROM students WHERE group_id=$1 AND teacher_id IS NOT NULL "
            "GROUP BY teacher_id, teacher_name, region",
            group_id,
        )

    if not rows:
        return await update.message.reply_text("Hozircha hech kim ro'yxat qo'shmagan.")

    tally = {}
    for r in rows:
        tid = r["teacher_id"]
        tally.setdefault(tid, {"name": r["teacher_name"], "count": 0, "regions": set()})
        tally[tid]["count"] += r["c"]
        tally[tid]["regions"].add(r["region"])

    ranked = sorted(tally.values(), key=lambda x: x["count"], reverse=True)
    lines = ["👨‍🏫 USTOZLAR BO'YICHA HISOBOT\n"]
    for i, t in enumerate(ranked, 1):
        regions_str = ", ".join(sorted(t["regions"]))
        lines.append(f"{i}. {t['name']} — {t['count']} nafar ({regions_str})")
    total_students = sum(t["count"] for t in ranked)
    lines.append(f"\n\nJami: {len(ranked)} ta ustoz, {total_students} nafar o'quvchi")

    await update.message.reply_text("\n".join(lines))


# ============================================================
#                    NATIJA VA REYTING
# ============================================================

async def cmd_natija(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /natija <kod> <bosqich> <ball>"""
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat admin uchun.")
    if len(context.args) < 3:
        return await update.message.reply_text(
            "Foydalanish: /natija <kod> <bosqich> <ball>\nMasalan: /natija AP-BUX-00123 1 87"
        )
    code, stage_str, score_str = context.args[0], context.args[1], context.args[2]
    try:
        stage = int(stage_str)
        score = int(score_str)
    except ValueError:
        return await update.message.reply_text("Bosqich va ball raqam bo'lishi kerak.")

    async with db_pool.acquire() as conn:
        student = await conn.fetchrow("SELECT name FROM students WHERE code=$1", code.upper())
        if not student:
            return await update.message.reply_text(f"❌ Kod topilmadi: {code}")
        await conn.execute(
            "INSERT INTO results (code, stage, score, entered_by) VALUES ($1,$2,$3,$4) "
            "ON CONFLICT (code, stage) DO UPDATE SET score=$3, entered_by=$4, created_at=NOW()",
            code.upper(), stage, score, update.effective_user.id,
        )
    await update.message.reply_text(
        f"✅ Saqlandi: {student['name']} ({code.upper()}) — {stage}-bosqich — {score} ball"
    )


async def cmd_natijalar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: ko'p natijani birdaniga kiritish. Reply qilingan xabarda har qatorda:
    KOD BALL (masalan: AP-BUX-00123 87)"""
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat admin uchun.")
    if not context.args:
        return await update.message.reply_text("Foydalanish: /natijalar <bosqich>  (reply qilib)")
    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        return await update.message.reply_text(
            "Har qatorda 'KOD BALL' bo'lgan xabarga reply qilib /natijalar <bosqich> deb yozing."
        )
    try:
        stage = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("Bosqich raqam bo'lishi kerak.")

    lines = update.message.reply_to_message.text.split("\n")
    saved, failed = 0, []

    async with db_pool.acquire() as conn:
        for line in lines:
            parts = line.strip().split()
            if len(parts) < 2:
                if line.strip():
                    failed.append(line.strip())
                continue
            code, score_str = parts[0].upper(), parts[1]
            try:
                score = int(score_str)
            except ValueError:
                failed.append(line.strip())
                continue
            student = await conn.fetchrow("SELECT 1 FROM students WHERE code=$1", code)
            if not student:
                failed.append(f"{line.strip()} (kod topilmadi)")
                continue
            await conn.execute(
                "INSERT INTO results (code, stage, score, entered_by) VALUES ($1,$2,$3,$4) "
                "ON CONFLICT (code, stage) DO UPDATE SET score=$3, entered_by=$4, created_at=NOW()",
                code, stage, score, update.effective_user.id,
            )
            saved += 1

    summary = [f"✅ {saved} ta natija saqlandi ({stage}-bosqich)."]
    if failed:
        summary.append(f"\n⚠️ {len(failed)} ta qator saqlanmadi:")
        summary.extend(failed[:15])
    await update.message.reply_text("\n".join(summary))


async def cmd_natijam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Har kim: /natijam <kod> — birinchi marta kanal tekshiruvidan o'tadi."""
    if not context.args:
        return await update.message.reply_text("Foydalanish: /natijam <kod>\nMasalan: /natijam AP-BUX-00123")

    user = update.effective_user

    # Birinchi marta tekshirish (B-variant: bir marta tasdiqlansa keyin erkin)
    async with db_pool.acquire() as conn:
        verified = await conn.fetchval("SELECT 1 FROM verified_users WHERE user_id=$1", user.id)

    if not verified:
        missing = await get_missing_channels(context, user.id, DEFAULT_GROUP_ID) if DEFAULT_GROUP_ID else []
        if missing:
            keyboard = build_keyboard(missing, user.id)
            return await update.message.reply_text(
                "Natijani ko'rish uchun avval quyidagi kanal(lar)ga qo'shiling:",
                reply_markup=keyboard,
            )
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO verified_users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user.id
            )

    code = context.args[0].upper()
    async with db_pool.acquire() as conn:
        student = await conn.fetchrow(
            "SELECT name, age, category, region FROM students WHERE code=$1", code
        )
        if not student:
            return await update.message.reply_text(f"❌ Bunday kod topilmadi: {code}")
        results = await conn.fetch(
            "SELECT stage, score FROM results WHERE code=$1 ORDER BY stage", code
        )

    lines = [
        f"🏆 {student['name']}",
        f"Yosh: {student['age']} ({student['category']})",
        f"Hudud: {student['region']}",
        f"Kod: {code}\n",
    ]
    if not results:
        lines.append("Hozircha natija kiritilmagan.")
    else:
        for r in results:
            lines.append(f"{r['stage']}-bosqich: {r['score']} ball")

    await update.message.reply_text("\n".join(lines))


async def cmd_reyting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reyting <toifa> [viloyat] [bosqich] — standart: eng oxirgi bosqich"""
    if not context.args:
        return await update.message.reply_text(
            "Foydalanish: /reyting <toifa> [viloyat]\nMasalan: /reyting 7-8 Buxoro"
        )

    user = update.effective_user
    async with db_pool.acquire() as conn:
        verified = await conn.fetchval("SELECT 1 FROM verified_users WHERE user_id=$1", user.id)

    if not verified:
        missing = await get_missing_channels(context, user.id, DEFAULT_GROUP_ID) if DEFAULT_GROUP_ID else []
        if missing:
            keyboard = build_keyboard(missing, user.id)
            return await update.message.reply_text(
                "Reytingni ko'rish uchun avval quyidagi kanal(lar)ga qo'shiling:",
                reply_markup=keyboard,
            )
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO verified_users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user.id
            )

    cat_input = context.args[0]
    region_filter = " ".join(context.args[1:]) if len(context.args) > 1 else None

    cat_match = None
    for c in AGE_CATEGORIES:
        if c.startswith(cat_input) or cat_input in c:
            cat_match = c
            break
    if not cat_match:
        return await update.message.reply_text(
            "Toifa topilmadi. Variantlar: " + ", ".join(AGE_CATEGORIES)
        )

    group_id = roster_target_chat_id(update)

    query = """
        SELECT s.code, s.name, s.region, r.stage, r.score
        FROM students s
        JOIN results r ON r.code = s.code
        WHERE s.group_id=$1 AND s.category=$2
    """
    params = [group_id, cat_match]
    if region_filter:
        query += " AND LOWER(s.region)=LOWER($3)"
        params.append(region_filter)
    query += " ORDER BY r.stage DESC, r.score DESC"

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    if not rows:
        return await update.message.reply_text("Hozircha shu toifada natija yo'q.")

    latest_stage = rows[0]["stage"]
    filtered = [r for r in rows if r["stage"] == latest_stage]

    lines = [f"🏆 REYTING — {cat_match}" + (f" ({region_filter})" if region_filter else "")]
    lines.append(f"{latest_stage}-bosqich\n")
    for i, r in enumerate(filtered[:30], 1):
        lines.append(f"{i}. {r['name']} — {r['score']} ball ({r['region']})")
    if len(filtered) > 30:
        lines.append(f"\n... va yana {len(filtered) - 30} nafar")

    await update.message.reply_text("\n".join(lines))


# ============================================================
#                    START
# ============================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_owner = user.id == OWNER_ID

    text = (
        f"Assalomu alaykum, {user.first_name}! 👋\n\n"
        f"Men — <b>AbacusPrime</b> botiman.\n\n"
    )

    if is_owner:
        text += (
            "<b>📋 ADMIN BUYRUQLARI</b>\n\n"
            "<u>Kanallar:</u>\n"
            "/addchannel &lt;id&gt; &lt;nom&gt;\n"
            "/removechannel &lt;id&gt;\n"
            "/listchannels\n"
            "/setmessage — (reply)\n\n"
            "<u>Ro'yxat:</u>\n"
            "/royhat &lt;viloyat&gt; — (reply)\n"
            "/royhatlar [viloyat]\n"
            "/royhatdanchiqar &lt;viloyat&gt; — (reply)\n"
            "/royhattozala [viloyat]\n"
            "/ustozlar\n\n"
            "<u>Natija:</u>\n"
            "/natija &lt;kod&gt; &lt;bosqich&gt; &lt;ball&gt;\n"
            "/natijalar &lt;bosqich&gt; — (reply, ko'p natija birdaniga)\n"
            "/reyting &lt;toifa&gt; [viloyat]\n\n"
            "/id\n"
        )
    else:
        text += (
            "👨‍🏫 <b>USTOZLAR</b> — o'quvchilar ro'yxatini yuborish uchun, ro'yxat xabariga "
            "reply qilib: <code>/royhat Viloyat_nomi</code>\n"
            "O'zingiz qo'shganlarni ko'rish: /royhatlarim\n\n"
            "👨‍👩‍👦 <b>OTA-ONALAR</b> — farzandingiz kodi bilan natijani ko'rish: "
            "<code>/natijam KOD</code>\n"
            "Reytingni ko'rish: <code>/reyting 7-8</code>\n\n"
            "📸 Instagram sahifamizga obuna bo'lganingiz haqida skrinshotni shu yerga yuboring."
        )

    await update.message.reply_text(text, parse_mode="HTML")


# ============================================================
#                    MAIN
# ============================================================

def main():
    if not BOT_TOKEN or not OWNER_ID:
        raise SystemExit("BOT_TOKEN yoki OWNER_ID topilmadi! Variables bo'limini tekshiring.")
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL topilmadi! Railway'da PostgreSQL qo'shib, ulang.")

    app = Application.builder().token(BOT_TOKEN).post_init(init_db).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("addchannel", cmd_addchannel))
    app.add_handler(CommandHandler("removechannel", cmd_removechannel))
    app.add_handler(CommandHandler("listchannels", cmd_listchannels))
    app.add_handler(CommandHandler("setmessage", cmd_setmessage))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("royhat", cmd_royhat))
    app.add_handler(CommandHandler("royhatlarim", cmd_royhatlarim))
    app.add_handler(CommandHandler("royhatlar", cmd_royhatlar))
    app.add_handler(CommandHandler("royhatdanchiqar", cmd_royhatdanchiqar))
    app.add_handler(CommandHandler("royhattozala", cmd_royhattozala))
    app.add_handler(CommandHandler("ustozlar", cmd_ustozlar))
    app.add_handler(CommandHandler("natija", cmd_natija))
    app.add_handler(CommandHandler("natijalar", cmd_natijalar))
    app.add_handler(CommandHandler("natijam", cmd_natijam))
    app.add_handler(CommandHandler("reyting", cmd_reyting))

    app.add_handler(CallbackQueryHandler(on_check_button, pattern=r"^check:"))
    app.add_handler(CallbackQueryHandler(on_instagram_decision, pattern=r"^ig(ok|no):"))

    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
        on_service_message,
    ))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, on_instagram_screenshot))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, on_message))

    logger.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
