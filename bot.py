import os
import logging
import sqlite3
import asyncio
import threading
import httpx
import qrcode
from io import BytesIO
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ================== CONFIG ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
PORT = int(os.environ.get("PORT", 8080))

BAN_API_BASE = "https://jexarcodexacstoban.vercel.app/close?access_token="
API_KEY = "ANIXH"
DEVELOPER_USERNAME = "@SYNTHX_ERRORR"
DEVELOPER_LINK = "https://t.me/SYNTHX_ERRORR"

DB_PATH = "bot_data.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ================== HEALTH SERVER (Render ke liye) ==================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h1>Bot is running!</h1>")

    def log_message(self, format, *args):
        pass  # silence logs


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info(f"Health server running on port {PORT}")
    server.serve_forever()


# ================== DATABASE ==================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            link TEXT,
            first_seen TEXT,
            last_seen TEXT,
            is_approved INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            usage_count INTEGER DEFAULT 0
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS bans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            game_uid TEXT,
            game_name TEXT,
            banned_at TEXT,
            banned_by INTEGER
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )"""
    )
    conn.commit()
    conn.close()


init_db()


def get_setting(key, default=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def is_user_banned(user_id):
    u = get_user(user_id)
    if not u:
        return False
    # index 8 = is_banned
    return u[8] == 1


def is_user_approved(user_id):
    u = get_user(user_id)
    if not u:
        return False
    # index 7 = is_approved
    return u[7] == 1


# ================== HELPERS ==================
async def notify_owner(context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    try:
        await context.bot.send_message(
            chat_id=OWNER_ID, text=text, reply_markup=reply_markup, parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Owner notify failed: {e}")


def generate_upi_qr(upi_id: str, amount: float, name: str = "Owner"):
    upi_url = f"upi://pay?pa={upi_id}&pn={name}&am={amount}&cu=INR"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(upi_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio


async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    link = f"tg://user?id={user.id}"

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, usage_count FROM users WHERE user_id=?", (user.id,))
    row = c.fetchone()

    if row:
        new_count = (row[1] or 0) + 1
        c.execute(
            "UPDATE users SET last_seen=?, username=?, first_name=?, last_name=?, link=?, usage_count=? WHERE user_id=?",
            (now, user.username, user.first_name, user.last_name, link, new_count, user.id),
        )
        conn.commit()
        conn.close()
        # Notify owner on every use
        if user.id != OWNER_ID:
            await notify_owner(
                context,
                f"🔔 <b>Bot Used</b>\n\n"
                f"👤 {user.first_name} (@{user.username or 'no_user'})\n"
                f"🆔 <code>{user.id}</code>\n"
                f"🔗 {link}\n"
                f"⏰ {now}\n"
                f"📊 Usage Count: {new_count}",
            )
    else:
        c.execute(
            "INSERT INTO users (user_id, username, first_name, last_name, link, first_seen, last_seen, usage_count) VALUES (?,?,?,?,?,?,?,?)",
            (user.id, user.username, user.first_name, user.last_name, link, now, now, 1),
        )
        conn.commit()
        conn.close()
        if user.id != OWNER_ID:
            await notify_owner(
                context,
                f"🆕 <b>New User Started Bot</b>\n\n"
                f"👤 {user.first_name} {user.last_name or ''}\n"
                f"🆔 <code>{user.id}</code>\n"
                f"🔗 {link}\n"
                f"⏰ {now}",
            )


# ================== START ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id != OWNER_ID and is_user_banned(user.id):
        await update.message.reply_text(
            f"❌ You are banned from using this bot.\nContact {DEVELOPER_USERNAME}"
        )
        return

    await track_user(update, context)

    welcome_img = get_setting("welcome_image")
    text = (
        f"👋 <b>Welcome {user.first_name}!</b>\n\n"
        f"🆔 Your ID: <code>{user.id}</code>\n"
        f"👨‍💻 Developer: {DEVELOPER_USERNAME}\n\n"
        f"⚔️ <i>This bot is used for banning FF accounts.</i>"
    )

    kb = [
        [InlineKeyboardButton("🔨 BAN ACCOUNT", callback_data="ban_account_start")],
        [InlineKeyboardButton("👨‍💻 Developer", url=DEVELOPER_LINK)],
    ]
    if user.id == OWNER_ID:
        kb.append([InlineKeyboardButton("👑 Owner Panel", callback_data="owner_panel")])

    reply_markup = InlineKeyboardMarkup(kb)

    if welcome_img:
        try:
            await update.message.reply_photo(
                photo=welcome_img,
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
            return
        except Exception as e:
            logger.error(f"Welcome image send failed: {e}")

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


# ================== BAN FLOW ==================
async def ban_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if user_id != OWNER_ID and is_user_banned(user_id):
        await query.edit_message_text(
            f"❌ You are banned from using this bot.\nContact {DEVELOPER_USERNAME}"
        )
        return

    await query.edit_message_text(
        "🔑 <b>Send your Access Token</b>\n\n"
        "Please send the Access Token of the account you want to ban.\n"
        "⚠️ Make sure it is correct, otherwise the ban will fail.",
        parse_mode="HTML",
    )
    context.user_data["awaiting_token"] = True


async def handle_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text.strip()
    context.user_data["awaiting_token"] = False

    if not token:
        await update.message.reply_text("❌ Invalid token. Try again.")
        return

    context.user_data["target_token"] = token

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ YES, BAN", callback_data="confirm_ban_yes")],
            [InlineKeyboardButton("❌ CANCEL", callback_data="confirm_ban_no")],
        ]
    )
    await update.message.reply_text(
        "⚠️ <b>Are you 100% sure to ban this account?</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def confirm_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_ban_no":
        await query.edit_message_text("❌ Ban cancelled.")
        context.user_data.pop("target_token", None)
        return

    user_id = query.from_user.id
    price = get_setting("ban_price", "0")

    # Agar price set hai aur user approved nahi hai -> payment maango
    if price and price != "0" and not is_user_approved(user_id):
        upi_id = get_setting("upi_id", "example@upi")
        holder = get_setting("holder_name", "Owner")
        try:
            qr_bio = generate_upi_qr(upi_id, float(price), holder)
            await query.edit_message_text(
                f"💰 <b>Payment Required</b>\n\n"
                f"Amount: ₹{price}\n"
                f"UPI ID: <code>{upi_id}</code>\n"
                f"Account Holder: {holder}\n\n"
                f"Scan the QR below, then click 'Confirm Payment'.",
                parse_mode="HTML",
            )
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=InputFile(qr_bio, filename="qr.png"),
                caption=f"Pay ₹{price} to {holder}\nUPI: {upi_id}",
            )
            kb = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✅ Confirm Payment", callback_data="payment_done")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="payment_cancel")],
                ]
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="After paying, click below:",
                reply_markup=kb,
            )
        except Exception as e:
            logger.error(f"QR generate failed: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id, text="❌ Payment setup error. Contact admin."
            )
        return

    await execute_ban(query, context)


async def execute_ban(query_or_update, context: ContextTypes.DEFAULT_TYPE):
    token = context.user_data.get("target_token")
    if not token:
        await context.bot.send_message(
            chat_id=query_or_update.message.chat_id, text="❌ Token missing. Start again."
        )
        return

    api_url = f"{BAN_API_BASE}{token}&key={API_KEY}"
    success = False
    game_name = "Unknown"
    game_uid = "Unknown"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(api_url)
            logger.info(f"API status: {resp.status_code}, body: {resp.text[:300]}")
            try:
                data = resp.json()
            except Exception:
                data = {}

            success = data.get("success", resp.status_code == 200)
            game_name = data.get("name") or data.get("game_name") or "Unknown"
            game_uid = data.get("uid") or data.get("game_uid") or "Unknown"
    except Exception as e:
        logger.error(f"Ban API error: {e}")
        await context.bot.send_message(
            chat_id=query_or_update.message.chat_id,
            text=f"❌ Ban failed: API error.\n{str(e)}",
        )
        context.user_data.pop("target_token", None)
        return

    if success:
        user_id = query_or_update.from_user.id if hasattr(query_or_update, "from_user") else None
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO bans (user_id, game_uid, game_name, banned_at, banned_by) VALUES (?,?,?,?,?)",
            (user_id, game_uid, game_name, now, user_id),
        )
        conn.commit()
        conn.close()

        user_link = f"tg://user?id={user_id}"
        await notify_owner(
            context,
            f"🚫 <b>Account Banned</b>\n\n"
            f"👤 User: <a href='{user_link}'>User</a> (ID: {user_id})\n"
            f"🎮 Game Name: {game_name}\n"
            f"🆔 Game UID: <code>{game_uid}</code>\n"
            f"⏰ Time: {now}",
        )

        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔨 Ban Another", callback_data="ban_account_start")]]
        )
        await context.bot.send_message(
            chat_id=query_or_update.message.chat_id,
            text=(
                f"✅ <b>Account Banned!</b>\n\n"
                f"🎮 Name: {game_name}\n"
                f"🆔 UID: {game_uid}\n\n"
                f"👨‍💻 Developer: {DEVELOPER_USERNAME}"
            ),
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        await context.bot.send_message(
            chat_id=query_or_update.message.chat_id,
            text="❌ Ban failed. Check token or API response.",
        )

    context.user_data.pop("target_token", None)


# ================== PAYMENT FLOW ==================
async def payment_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📸 Please send the payment screenshot now.")
    context.user_data["awaiting_screenshot"] = True


async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    user = update.effective_user
    context.user_data["awaiting_screenshot"] = False

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}")],
            [InlineKeyboardButton("❌ Disapprove", callback_data=f"reject_{user.id}")],
        ]
    )
    await context.bot.send_photo(
        chat_id=OWNER_ID,
        photo=photo.file_id,
        caption=(
            f"💰 Payment Screenshot\n\n"
            f"👤 {user.first_name} (@{user.username or 'no_user'})\n"
            f"🆔 {user.id}\n"
            f"🔗 tg://user?id={user.id}"
        ),
        reply_markup=kb,
    )
    await update.message.reply_text("⏳ Wait for admin review. You will be notified.")


async def approve_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    action = parts[0]
    target_user_id = int(parts[1])

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if action == "approve":
        c.execute("UPDATE users SET is_approved=1 WHERE user_id=?", (target_user_id,))
        conn.commit()
        conn.close()
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="✅ Now you have unlimited access!\n\nYou can ban accounts without paying.",
            )
        except Exception as e:
            logger.error(f"Approve notify failed: {e}")
        await query.edit_message_caption(caption="✅ Approved.")
    else:
        c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (target_user_id,))
        conn.commit()
        conn.close()
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"❌ You are banned. Contact {DEVELOPER_USERNAME}",
            )
        except Exception as e:
            logger.error(f"Reject notify failed: {e}")
        await query.edit_message_caption(caption="❌ Disapproved.")


# ================== OWNER PANEL ==================
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await show_owner_panel(update.message.chat_id, context, edit=False)


async def show_owner_panel(chat_id, context, edit=False, message_id=None):
    kb = [
        [InlineKeyboardButton("👥 Total Users", callback_data="owner_stats")],
        [InlineKeyboardButton("📋 All Banned IDs", callback_data="owner_all_bans")],
        [InlineKeyboardButton("🚫 Ban User (by ID)", callback_data="owner_ban_user")],
        [InlineKeyboardButton("✅ Unban User (by ID)", callback_data="owner_unban_user")],
        [InlineKeyboardButton("🖼️ Set Welcome Image", callback_data="owner_set_welcome")],
        [InlineKeyboardButton("💰 Set Ban Price", callback_data="owner_set_price")],
        [InlineKeyboardButton("🏦 Set UPI ID", callback_data="owner_set_upi")],
        [InlineKeyboardButton("👤 Set Holder Name", callback_data="owner_set_holder")],
    ]
    text = (
        f"👑 <b>Owner Panel</b>\n\n"
        f"💰 Ban Price: ₹{get_setting('ban_price', 'Not set')}\n"
        f"🏦 UPI ID: {get_setting('upi_id', 'Not set')}\n"
        f"👤 Holder: {get_setting('holder_name', 'Not set')}"
    )
    markup = InlineKeyboardMarkup(kb)
    if edit and message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup, parse_mode="HTML"
            )
            return
        except Exception:
            pass
    await context.bot.send_message(
        chat_id=chat_id, text=text, reply_markup=markup, parse_mode="HTML"
    )


# ================== CALLBACK ROUTER ==================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    if data == "ban_account_start":
        await ban_account_start(update, context)
    elif data == "confirm_ban_yes":
        await confirm_ban(update, context)
    elif data == "confirm_ban_no":
        await query.edit_message_text("❌ Cancelled.")
    elif data == "payment_done":
        await payment_done(update, context)
    elif data == "payment_cancel":
        await query.edit_message_text("❌ Payment cancelled.")
    elif data.startswith("approve_") or data.startswith("reject_"):
        if user_id == OWNER_ID:
            await approve_payment(update, context)
    elif data == "owner_panel":
        if user_id == OWNER_ID:
            await show_owner_panel(query.message.chat_id, context, edit=True, message_id=query.message.message_id)
    elif data == "owner_stats":
        if user_id != OWNER_ID:
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM bans")
        bans = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE is_approved=1")
        approved = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE is_banned=1")
        banned = c.fetchone()[0]
        conn.close()
        await query.edit_message_text(
            f"👥 <b>Bot Stats</b>\n\n"
            f"Total Users: {total}\n"
            f"Approved Users: {approved}\n"
            f"Banned Users: {banned}\n"
            f"Total Bans: {bans}",
            parse_mode="HTML",
        )
    elif data == "owner_all_bans":
        if user_id != OWNER_ID:
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT game_uid, game_name, banned_at FROM bans ORDER BY id DESC LIMIT 50")
        rows = c.fetchall()
        conn.close()
        if not rows:
            await query.edit_message_text("No bans recorded.")
        else:
            txt = "📋 <b>Recent Bans (Last 50)</b>\n\n"
            for i, r in enumerate(rows, 1):
                txt += f"{i}. 🆔 {r[0]} | 🎮 {r[1]} | ⏰ {r[2]}\n"
            await query.edit_message_text(txt, parse_mode="HTML")
    elif data == "owner_set_welcome":
        if user_id != OWNER_ID:
            return
        await query.edit_message_text("📸 Send the photo you want as welcome image.")
        context.user_data["owner_action"] = "set_welcome"
    elif data == "owner_set_price":
        if user_id != OWNER_ID:
            return
        await query.edit_message_text("💰 Send the ban price (number only, e.g., 50).")
        context.user_data["owner_action"] = "set_price"
    elif data == "owner_set_upi":
        if user_id != OWNER_ID:
            return
        await query.edit_message_text("🏦 Send your UPI ID (e.g., name@upi).")
        context.user_data["owner_action"] = "set_upi"
    elif data == "owner_set_holder":
        if user_id != OWNER_ID:
            return
        await query.edit_message_text("👤 Send account holder name.")
        context.user_data["owner_action"] = "set_holder"
    elif data == "owner_ban_user":
        if user_id != OWNER_ID:
            return
        await query.edit_message_text("🚫 Send the User ID to ban from using this bot.")
        context.user_data["owner_action"] = "ban_user"
    elif data == "owner_unban_user":
        if user_id != OWNER_ID:
            return
        await query.edit_message_text("✅ Send the User ID to unban.")
        context.user_data["owner_action"] = "unban_user"


# ================== MESSAGE HANDLER ==================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text if update.message.text else None
    photo = update.message.photo if update.message.photo else None

    # Owner Actions
    if user_id == OWNER_ID and context.user_data.get("owner_action"):
        action = context.user_data["owner_action"]
        context.user_data["owner_action"] = None
        if action == "set_welcome" and photo:
            set_setting("welcome_image", photo[-1].file_id)
            await update.message.reply_text("✅ Welcome image set.")
        elif action == "set_price" and text:
            try:
                float(text)
                set_setting("ban_price", text)
                await update.message.reply_text(f"✅ Ban price set to ₹{text}.")
            except ValueError:
                await update.message.reply_text("❌ Invalid number.")
        elif action == "set_upi" and text:
            set_setting("upi_id", text)
            await update.message.reply_text(f"✅ UPI ID set to {text}.")
        elif action == "set_holder" and text:
            set_setting("holder_name", text)
            await update.message.reply_text(f"✅ Holder name set to {text}.")
        elif action == "ban_user" and text:
            try:
                target = int(text)
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (target,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ User {target} banned from bot.")
            except ValueError:
                await update.message.reply_text("❌ Invalid ID.")
        elif action == "unban_user" and text:
            try:
                target = int(text)
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (target,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ User {target} unbanned.")
            except ValueError:
                await update.message.reply_text("❌ Invalid ID.")
        return

    # Screenshot
    if context.user_data.get("awaiting_screenshot") and photo:
        await handle_screenshot(update, context)
        return

    # Token
    if context.user_data.get("awaiting_token") and text:
        await handle_token(update, context)
        return


# ================== MAIN ==================
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing!")
        return
    if not OWNER_ID:
        logger.error("OWNER_ID missing!")
        return

    # Start health server in background thread (Render ke liye zaroori)
    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("owner", owner_panel))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))

    logger.info("Bot starting polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
