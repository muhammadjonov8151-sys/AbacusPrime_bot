"""
AbacusPrime Force-Subscribe Bot
Guruhga yozish uchun odamlarni bir nechta kanalga a'zo bo'lishga majburlaydi,
har bir kanal uchun O'ZINGIZ BELGILAGAN nom bilan tugma chiqaradi
(Join 1 / Join 2 emas, masalan "Haramayn Store" yoki "VAQF" kabi).

O'rnatish:
    pip install python-telegram-bot==21.* --break-system-packages

Ishga tushirish:
    python3 bot.py

Sozlash: BOT_TOKEN va OWNER_ID ni pastda to'ldiring.
"""

import asyncio
import json
import os
import logging
import re
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
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
# Bu ikkisini kodga yozmaymiz — hosting xizmatida "Variables" bo'limiga qo'yamiz.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
CONFIG_FILE = os.environ.get(
    "CONFIG_PATH",
    os.path.join(os.path.dirname(__file__), "config.json"),
)
DEFAULT_MESSAGE = (
    "Hurmatli {mention}!\n\n"
    "Guruhda yozish uchun avval quyidagi kanal(lar)ga qo'shiling, "
    "so'ng \"✅ Tekshirish\" tugmasini bosing!"
)

# ============ DOIMIY KANALLAR RO'YXATI ============
# Bu ro'yxat har safar bot qayta ishga tushganda avtomatik tiklanadi —
# Railway serverining vaqtinchalik xotirasi tozalansa ham yo'qolmaydi,
# chunki bu GitHub'dagi kodning ichida saqlanadi.
#
# Guruh ID'sini guruh ichida /id buyrug'i orqali oling.
# Kanal ID'sini kanal ichida /id buyrug'i orqali oling.
DEFAULT_GROUP_ID = -1003939400499  # AbacusPrime guruhi
DEFAULT_CHANNELS = [
    {"id": -1003986384293, "name": "AbacusPrime"},
    {"id": -1004349040226, "name": "Haramayn_store"},
    {"id": -1003936814449, "name": "Haramayn_Vaqf"},
]
# =====================================


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"groups": {}}


def save_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_FILE) or ".", exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_group_cfg(cfg: dict, chat_id: int) -> dict:
    key = str(chat_id)
    if key not in cfg["groups"]:
        cfg["groups"][key] = {"channels": [], "message": DEFAULT_MESSAGE}
    return cfg["groups"][key]


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user.id == OWNER_ID:
        return True
    member = await context.bot.get_chat_member(update.effective_chat.id, user.id)
    return member.status in ("administrator", "creator")


# ---------- ADMIN BUYRUQLARI ----------

async def cmd_addchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/addchannel -1001234567890 Haramayn Store"""
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")

    if len(context.args) < 2:
        return await update.message.reply_text(
            "Foydalanish: /addchannel <kanal_id> <tugma_nomi>\n"
            "Masalan: /addchannel -1001234567890 Haramayn Store"
        )

    channel_id = context.args[0]
    button_name = " ".join(context.args[1:])

    try:
        channel_id_int = int(channel_id)
    except ValueError:
        return await update.message.reply_text("Kanal ID raqam bo'lishi kerak, masalan -1001234567890")

    # Bot o'sha kanalda admin ekanini tekshiramiz
    try:
        chat = await context.bot.get_chat(channel_id_int)
        invite_link = chat.invite_link
        if not invite_link:
            invite_link = await context.bot.export_chat_invite_link(channel_id_int)
    except Exception as e:
        return await update.message.reply_text(
            f"Xatolik: bot shu kanalda admin emas yoki ID noto'g'ri.\n{e}"
        )

    cfg = load_config()
    gcfg = get_group_cfg(cfg, update.effective_chat.id)
    gcfg["channels"] = [c for c in gcfg["channels"] if c["id"] != channel_id_int]
    gcfg["channels"].append({
        "id": channel_id_int,
        "name": button_name,
        "invite_link": invite_link,
    })
    save_config(cfg)

    await update.message.reply_text(f"✅ Qo'shildi: \"{button_name}\" ({channel_id_int})")


async def cmd_removechannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/removechannel -1001234567890"""
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")

    if not context.args:
        return await update.message.reply_text("Foydalanish: /removechannel <kanal_id>")

    try:
        channel_id_int = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("Kanal ID raqam bo'lishi kerak.")

    cfg = load_config()
    gcfg = get_group_cfg(cfg, update.effective_chat.id)
    before = len(gcfg["channels"])
    gcfg["channels"] = [c for c in gcfg["channels"] if c["id"] != channel_id_int]
    save_config(cfg)

    if len(gcfg["channels"]) < before:
        await update.message.reply_text("✅ O'chirildi.")
    else:
        await update.message.reply_text("Bunday kanal topilmadi.")


async def cmd_listchannels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = load_config()
    gcfg = get_group_cfg(cfg, update.effective_chat.id)
    if not gcfg["channels"]:
        return await update.message.reply_text("Hozircha kanal qo'shilmagan.")
    lines = [f"• {c['name']} — {c['id']}" for c in gcfg["channels"]]
    await update.message.reply_text("Talab qilinadigan kanallar:\n" + "\n".join(lines))


async def cmd_setmessage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply qilib: /setmessage"""
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")

    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        return await update.message.reply_text(
            "Avval xabar matnini yuboring, so'ng o'sha xabarga javob (reply) qilib /setmessage yozing.\n"
            "Foydalanuvchi ismini avtomatik qo'yish uchun {mention} yozing."
        )

    cfg = load_config()
    gcfg = get_group_cfg(cfg, update.effective_chat.id)
    gcfg["message"] = update.message.reply_to_message.text
    save_config(cfg)
    await update.message.reply_text("✅ Xabar matni saqlandi.")


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID: `{update.effective_chat.id}`", parse_mode="Markdown")


# ---------- YOSH BO'YICHA RO'YXAT TARTIBLASH ----------

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
    """'Aliyev Vali - 8 yosh' kabi qatordan (ism, yosh) ni ajratadi."""
    line = line.strip()
    if not line:
        return None
    # Boshidagi raqamlashni olib tashlaymiz: "1.", "2)"
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


async def cmd_royhat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply qilingan ro'yxatni, ko'rsatilgan viloyat ostida, yosh bo'yicha
    tartiblab saqlaydi. Foydalanish: xabarga reply qilib /royhat Buxoro"""
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")

    if not context.args:
        return await update.message.reply_text(
            "Viloyat nomini ko'rsating. Masalan:\n"
            "Avval ro'yxat xabariga reply qilib: /royhat Buxoro"
        )

    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        return await update.message.reply_text(
            "Avval o'quvchilar ro'yxatini (har qatorda 1 ta: Ism Familiya - yosh) yuboring, "
            "so'ng o'sha xabarga javob (reply) qilib /royhat <viloyat> deb yozing."
        )

    region_input = " ".join(context.args).strip()

    lines = update.message.reply_to_message.text.split("\n")
    cfg = load_config()
    gcfg = get_group_cfg(cfg, update.effective_chat.id)
    if "roster" not in gcfg:
        gcfg["roster"] = {}

    # Viloyat nomini katta-kichik harflarga qaramay mavjud kalitga moslashtiramiz
    region = region_input
    for existing in gcfg["roster"].keys():
        if existing.lower() == region_input.lower():
            region = existing
            break
    gcfg["roster"].setdefault(region, {})

    added = 0
    failed_lines = []
    for line in lines:
        parsed = parse_roster_line(line)
        if not parsed:
            if line.strip():
                failed_lines.append(line.strip())
            continue
        name, age = parsed
        cat = age_category(age)
        gcfg["roster"][region].setdefault(cat, [])
        gcfg["roster"][region][cat].append({"name": name, "age": age})
        added += 1

    save_config(cfg)

    summary_lines = [f"✅ {region} — {added} ta o'quvchi qo'shildi.\n"]
    for cat in ["5-6 yosh", "7-8 yosh", "9-10 yosh", "11+ yosh"]:
        count = len(gcfg["roster"][region].get(cat, []))
        summary_lines.append(f"• {cat}: {count} nafar")

    region_total = sum(len(v) for v in gcfg["roster"][region].values())
    summary_lines.append(f"\n{region} bo'yicha jami: {region_total} nafar")

    if failed_lines:
        summary_lines.append(f"\n⚠️ {len(failed_lines)} ta qator tushunilmadi:")
        for fl in failed_lines[:10]:
            summary_lines.append(f"— {fl}")

    await update.message.reply_text("\n".join(summary_lines))


async def cmd_royhatdanchiqar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bitta o'quvchini ro'yxatdan olib tashlaydi.
    Foydalanish: 'Aliyev Vali - 8 yosh' xabariga reply qilib /royhatdanchiqar Buxoro"""
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")

    if not context.args:
        return await update.message.reply_text(
            "Viloyat nomini ko'rsating. Masalan:\n"
            "'Aliyev Vali - 8 yosh' deb yozilgan xabarga reply qilib: /royhatdanchiqar Buxoro"
        )

    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        return await update.message.reply_text(
            "O'chirmoqchi bo'lgan o'quvchining ismi va yoshini (masalan 'Aliyev Vali - 8 yosh') "
            "alohida xabar qilib yuboring, so'ng o'sha xabarga reply qilib /royhatdanchiqar <viloyat> deb yozing."
        )

    region_input = " ".join(context.args).strip()
    parsed = parse_roster_line(update.message.reply_to_message.text.split("\n")[0])
    if not parsed:
        return await update.message.reply_text("Ism va yoshni tushuna olmadim. Format: Ism Familiya - yosh")

    target_name, target_age = parsed
    cfg = load_config()
    gcfg = get_group_cfg(cfg, update.effective_chat.id)
    roster = gcfg.get("roster", {})

    region = None
    for existing in roster.keys():
        if existing.lower() == region_input.lower():
            region = existing
            break
    if not region:
        return await update.message.reply_text(f"'{region_input}' nomli viloyat ro'yxati topilmadi.")

    cat = age_category(target_age)
    students = roster[region].get(cat, [])
    for i, s in enumerate(students):
        if s["name"].lower() == target_name.lower() and s["age"] == target_age:
            students.pop(i)
            save_config(cfg)
            return await update.message.reply_text(
                f"✅ {target_name} ({target_age} yosh) {region} ro'yxatidan olib tashlandi."
            )

    await update.message.reply_text(
        f"❌ {target_name} ({target_age} yosh) {region} ro'yxatida topilmadi."
    )


async def cmd_royhatlar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ro'yxatni fayl qilib chiqaradi. Argumentsiz — barcha viloyatlar,
    argument bilan (masalan /royhatlar Buxoro) — faqat o'sha viloyat."""
    cfg = load_config()
    gcfg = get_group_cfg(cfg, update.effective_chat.id)
    roster = gcfg.get("roster", {})

    if not roster:
        return await update.message.reply_text("Hozircha ro'yxat yo'q.")

    only_region = " ".join(context.args).strip() if context.args else None
    if only_region:
        match = None
        for existing in roster.keys():
            if existing.lower() == only_region.lower():
                match = existing
                break
        if not match:
            return await update.message.reply_text(f"'{only_region}' nomli viloyat ro'yxati topilmadi.")
        regions_to_export = {match: roster[match]}
    else:
        regions_to_export = roster

    lines = ["ABACUSPRIME — ISHTIROKCHILAR RO'YXATI\n"]
    grand_total = 0
    for region, cats in regions_to_export.items():
        region_total = sum(len(v) for v in cats.values())
        if region_total == 0:
            continue
        lines.append(f"\n\n########## {region.upper()} ({region_total} nafar) ##########")
        for cat in ["5-6 yosh", "7-8 yosh", "9-10 yosh", "11+ yosh"]:
            students = cats.get(cat, [])
            if not students:
                continue
            lines.append(f"\n=== {cat} ({len(students)} nafar) ===")
            for i, s in enumerate(students, 1):
                lines.append(f"{i}. {s['name']} — {s['age']} yosh")
        grand_total += region_total

    lines.append(f"\n\n\nUMUMIY JAMI: {grand_total} nafar")

    text_content = "\n".join(lines)
    file_path = f"/tmp/royhat_{update.effective_chat.id}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text_content)

    await update.message.reply_document(
        document=open(file_path, "rb"),
        filename="royhat.txt",
        caption=f"Jami: {grand_total} nafar o'quvchi.",
    )


async def cmd_royhattozala(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Argumentsiz — hammasini tozalaydi. Argument bilan (/royhattozala Buxoro) —
    faqat o'sha viloyatni tozalaydi."""
    if not await is_admin(update, context):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
    cfg = load_config()
    gcfg = get_group_cfg(cfg, update.effective_chat.id)

    if context.args:
        region_input = " ".join(context.args).strip()
        roster = gcfg.get("roster", {})
        region = None
        for existing in roster.keys():
            if existing.lower() == region_input.lower():
                region = existing
                break
        if not region:
            return await update.message.reply_text(f"'{region_input}' nomli viloyat ro'yxati topilmadi.")
        del roster[region]
        save_config(cfg)
        return await update.message.reply_text(f"✅ {region} ro'yxati tozalandi.")

    gcfg["roster"] = {}
    save_config(cfg)
    await update.message.reply_text("✅ Barcha viloyatlar ro'yxati tozalandi.")


# ---------- INSTAGRAM QO'LDA TASDIQLASH ----------

async def on_instagram_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi botga shaxsiy skrinshot yuborsa, adminga tekshirish uchun yuboradi."""
    user = update.effective_user
    if user.id == OWNER_ID:
        return  # Admin o'ziga skrinshot yuborsa e'tiborsiz qoldiramiz

    caption = (
        f"📸 Instagram tasdiqlash so'rovi\n\n"
        f"Kimdan: {user.mention_html()} (ID: {user.id})"
    )
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"igok:{user.id}"),
        InlineKeyboardButton("❌ Rad etish", callback_data=f"igno:{user.id}"),
    ]])

    await context.bot.send_photo(
        OWNER_ID,
        photo=update.message.photo[-1].file_id,
        caption=caption,
        parse_mode="HTML",
        reply_markup=buttons,
    )
    await update.message.reply_text("Skrinshotingiz adminга yuborildi, tez orada tekshiriladi. ⏳")


async def on_instagram_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != OWNER_ID:
        await query.answer("Bu tugma faqat admin uchun!", show_alert=True)
        return

    action, target_id_str = query.data.split(":", 1)
    target_id = int(target_id_str)

    if action == "igok":
        if DEFAULT_GROUP_ID:
            try:
                await context.bot.restrict_chat_member(
                    DEFAULT_GROUP_ID,
                    target_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_photos=True,
                        can_send_videos=True,
                        can_send_other_messages=True,
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
                target_id,
                "❌ Instagram skrinshoti tasdiqlanmadi. Iltimos, to'g'ri skrinshot bilan qayta urinib ko'ring.",
            )
        except Exception:
            pass
        await query.answer("Rad etildi.")
        await query.edit_message_caption(caption=query.message.caption + "\n\n❌ RAD ETILDI")


# ---------- ASOSIY LOGIKA ----------

async def get_missing_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int, channels: list) -> list:
    missing = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch["id"], user_id)
            if member.status in ("left", "kicked"):
                missing.append(ch)
        except Exception:
            missing.append(ch)
    return missing


# ============ INSTAGRAM SAHIFALAR ============
# Bu tugmalar faqat havola — avtomatik tekshirilmaydi, shunchaki odamlarni
# Instagram sahifalaringizga yo'naltiradi.
INSTAGRAM_LINKS = [
    {"name": "Haramayn.store", "url": "https://instagram.com/haramayn.store"},
    {"name": "AbacusPrime_", "url": "https://instagram.com/abacusprime_"},
]


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

    # Kanaldan avtomatik kelgan xabarlarni (linked channel post) tekshirmaymiz
    if update.message.sender_chat:
        return

    user = update.effective_user
    if user.is_bot:
        return

    member = await context.bot.get_chat_member(update.effective_chat.id, user.id)
    if member.status in ("administrator", "creator"):
        return

    cfg = load_config()
    gcfg = get_group_cfg(cfg, update.effective_chat.id)
    if not gcfg["channels"]:
        return

    missing = await get_missing_channels(context, user.id, gcfg["channels"])
    if not missing:
        return

    # Xabarni o'chiramiz va foydalanuvchini vaqtincha jim qilamiz
    try:
        await update.message.delete()
    except Exception:
        pass

    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            user.id,
            permissions=ChatPermissions(can_send_messages=False),
        )
    except Exception:
        pass

    mention = user.mention_html()
    text = gcfg["message"].replace("{mention}", mention)
    keyboard = build_keyboard(missing, user.id)

    try:
        # Avval shaxsiy xabar sifatida yuborishga harakat qilamiz
        await context.bot.send_message(
            user.id,
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception:
        # Foydalanuvchi botga hali "Start" bosmagan — guruhda to'liq xabar
        # (faqat shu foydalanuvchi tugmani bosa oladi, boshqalar bossa rad etiladi)
        warn = await context.bot.send_message(
            update.effective_chat.id,
            text + "\n\n<i>(Botga shaxsiy /start bossangiz, keyingi safar bu xabar faqat sizga yuboriladi)</i>",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        async def _auto_delete():
            await asyncio.sleep(300)  # 5 daqiqa
            try:
                await context.bot.delete_message(warn.chat_id, warn.message_id)
            except Exception:
                pass

        asyncio.create_task(_auto_delete())


async def on_check_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    # callback_data: "check:<target_user_id>"
    try:
        target_id = int(query.data.split(":", 1)[1])
    except (IndexError, ValueError):
        target_id = user.id

    if user.id != target_id:
        await query.answer("Bu tugma sizga tegishli emas!", show_alert=True)
        return

    # Bu xabar guruhdan keldimi yoki DM'danmi — ikkalasida ham chat_id kerak.
    # Guruh xabari bo'lsa, group_chat_id ni topamiz (query.message.chat_id guruh
    # bo'lishi ham, DM bo'lishi ham mumkin — buni saqlagan config orqali bilamiz).
    chat_id = query.message.chat_id
    is_group = query.message.chat.type in ("group", "supergroup")

    if is_group:
        group_chat_id = chat_id
    else:
        # DM orqali kelgan bo'lsa, foydalanuvchi qaysi guruhda cheklangani
        # xabar matnida saqlanmagani uchun, barcha guruhlardagi cheklovni
        # tekshirib, unmute qilamiz.
        cfg = load_config()
        group_chat_id = None
        for gid in cfg["groups"].keys():
            group_chat_id = int(gid)
            gcfg_ = get_group_cfg(cfg, group_chat_id)
            missing_ = await get_missing_channels(context, user.id, gcfg_["channels"])
            if not missing_:
                try:
                    await context.bot.restrict_chat_member(
                        group_chat_id,
                        user.id,
                        permissions=ChatPermissions(
                            can_send_messages=True,
                            can_send_photos=True,
                            can_send_videos=True,
                            can_send_other_messages=True,
                        ),
                    )
                except Exception:
                    pass
        await query.answer("Tabriklaymiz! Endi guruhda yozishingiz mumkin.", show_alert=True)
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    cfg = load_config()
    gcfg = get_group_cfg(cfg, group_chat_id)
    missing = await get_missing_channels(context, user.id, gcfg["channels"])

    if missing:
        await query.answer("Hali barcha kanallarga qo'shilmadingiz!", show_alert=True)
        await query.edit_message_reply_markup(reply_markup=build_keyboard(missing, user.id))
        return

    try:
        await context.bot.restrict_chat_member(
            group_chat_id,
            user.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_other_messages=True,
            ),
        )
    except Exception:
        pass

    await query.answer("Tabriklaymiz! Endi guruhda yozishingiz mumkin.", show_alert=True)
    try:
        await query.message.delete()
    except Exception:
        pass


async def on_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'X guruhga qo'shildi' / 'X guruhdan chiqdi' xabarlarini o'chiradi."""
    try:
        await update.message.delete()
    except Exception:
        pass


async def _seed_defaults(app):
    """Bot ishga tushganda DEFAULT_GROUP_ID/DEFAULT_CHANNELS asosida
    konfiguratsiyani avtomatik tiklaydi (fayl tozalanган bo'lsa ham)."""
    if not DEFAULT_GROUP_ID or not DEFAULT_CHANNELS:
        return
    cfg = load_config()
    gcfg = get_group_cfg(cfg, DEFAULT_GROUP_ID)
    existing_ids = {c["id"] for c in gcfg["channels"]}
    changed = False
    for ch in DEFAULT_CHANNELS:
        if ch["id"] in existing_ids:
            continue
        try:
            chat = await app.bot.get_chat(ch["id"])
            invite_link = chat.invite_link or await app.bot.export_chat_invite_link(ch["id"])
        except Exception as e:
            logger.warning(f"Standart kanal yuklanmadi ({ch['id']}): {e}")
            continue
        gcfg["channels"].append({"id": ch["id"], "name": ch["name"], "invite_link": invite_link})
        changed = True
    if changed:
        save_config(cfg)
        logger.info("Standart kanallar tiklandi.")


def main():
    if not BOT_TOKEN or not OWNER_ID:
        raise SystemExit(
            "BOT_TOKEN yoki OWNER_ID topilmadi! "
            "Hosting xizmatida 'Variables' bo'limiga BOT_TOKEN va OWNER_ID ni qo'shing."
        )
    app = Application.builder().token(BOT_TOKEN).post_init(_seed_defaults).build()

    app.add_handler(CommandHandler("addchannel", cmd_addchannel))
    app.add_handler(CommandHandler("removechannel", cmd_removechannel))
    app.add_handler(CommandHandler("listchannels", cmd_listchannels))
    app.add_handler(CommandHandler("setmessage", cmd_setmessage))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("royhat", cmd_royhat))
    app.add_handler(CommandHandler("royhatlar", cmd_royhatlar))
    app.add_handler(CommandHandler("royhatdanchiqar", cmd_royhatdanchiqar))
    app.add_handler(CommandHandler("royhattozala", cmd_royhattozala))
    app.add_handler(CallbackQueryHandler(on_check_button, pattern=r"^check:"))
    app.add_handler(CallbackQueryHandler(on_instagram_decision, pattern=r"^ig(ok|no):"))
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
        on_service_message,
    ))
    app.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.PRIVATE,
        on_instagram_screenshot,
    ))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, on_message))

    logger.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
