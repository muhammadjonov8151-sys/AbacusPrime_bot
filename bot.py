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

import json
import os
import logging
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
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
DEFAULT_MESSAGE = (
    "Hurmatli {mention}!\n\n"
    "Guruhda yozish uchun avval quyidagi kanal(lar)ga qo'shiling, "
    "so'ng \"✅ Tekshirish\" tugmasini bosing!"
)
# =====================================


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"groups": {}}


def save_config(cfg: dict) -> None:
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


def build_keyboard(missing: list, target_user_id: int) -> InlineKeyboardMarkup:
    buttons = []
    for ch in missing:
        buttons.append([InlineKeyboardButton(f"📢 {ch['name']}", url=ch["invite_link"])])
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


def main():
    if not BOT_TOKEN or not OWNER_ID:
        raise SystemExit(
            "BOT_TOKEN yoki OWNER_ID topilmadi! "
            "Hosting xizmatida 'Variables' bo'limiga BOT_TOKEN va OWNER_ID ni qo'shing."
        )
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("addchannel", cmd_addchannel))
    app.add_handler(CommandHandler("removechannel", cmd_removechannel))
    app.add_handler(CommandHandler("listchannels", cmd_listchannels))
    app.add_handler(CommandHandler("setmessage", cmd_setmessage))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CallbackQueryHandler(on_check_button, pattern="^check$"))
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
        on_service_message,
    ))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, on_message))

    logger.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
