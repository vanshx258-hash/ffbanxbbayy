import os
import logging
import sqlite3
import threading
import httpx
import qrcode
from io import BytesIO
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InputFile,
)
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
DEVELOPER_USERNAME = "𝐒𝐘𝐍𝐓𝐇𝐗_𝐄𝐑𝐑𝐎𝐑𝐑"
DEVELOPER_LINK = "https://t.me/SYNTHX_ERRORR"

DB_PATH = "bot_data.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ================== STYLISH TEXT ==================
def st(text: str) -> str:
    """Convert normal A-Z, a-z, 0-9 to stylish bold unicode."""
    upper_map = {
        "A": "𝐀", "B": "𝐁", "C": "𝐂", "D": "𝐃", "E": "𝐄", "F": "𝐅", "G": "𝐆",
        "H": "𝐇", "I": "𝐈", "J": "𝐉", "K": "𝐊", "L": "𝐋", "M": "𝐌", "N": "𝐍",
        "O": "𝐎", "P": "𝐏", "Q": "𝐐", "R": "𝐑", "S": "𝐒", "T": "𝐓", "U": "𝐔",
        "V": "𝐕", "W": "𝐖", "X": "𝐗", "Y": "𝐘", "Z": "𝐙",
    }
    lower_map = {
        "a": "𝐚", "b": "𝐛", "c": "𝐜", "d": "𝐝", "e": "𝐞", "f": "𝐟", "g": "𝐠",
        "h": "𝐡", "i": "𝐢", "j": "𝐣", "k": "𝐤", "l": "𝐥", "m": "𝐦", "n": "𝐧",
        "o": "𝐨", "p": "𝐩", "q": "𝐪", "r": "𝐫", "s": "𝐬", "t": "𝐭", "u": "𝐮",
        "v": "𝐯", "w": "𝐰", "x": "𝐱", "y": "𝐲", "z": "𝐳",
    }
    digit_map = {
        "0": "𝟎", "1": "𝟏", "2": "𝟐", "3": "𝟑", "4": "𝟒",
        "5": "𝟓", "6": "𝟔", "7": "𝟕", "8": "𝟖", "9": "𝟗",
    }
    out = []
    for ch in text:
        if ch in upper_map:
            out.append(upper_map[ch])
        elif ch in lower_map:
            out.append(lower_map[ch])
        elif ch in digit_map:
            out.append(digit_map[ch])
        else:
            out.append(ch)
    return "".join(out)


# ================== HEALTH SERVER ==================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h1>Bot is running!</h1>")

    def log_message(self, format, *args):
        pass


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
    return bool(u and u[8] == 1)


def is_user_approved(user_id):
    u = get_user(user_id)
    return bool(u and u[7] == 1)


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
        if user.id != OWNER_ID:
            await notify_owner(
                context,
                st("Bot Used") + "\n\n"
                + st("Name") + f": {user.first_name}\n"
                + st("Username") + f": @{user.username or 'no_user'}\n"
                + st("ID") + f": <code>{user.id}</code>\n"
                + st("Link") + f": {link}\n"
                + st("Time") + f": {now}\n"
                + st("Usage Count") + f": {new_count}",
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
                st("New User Started Bot") + "\n\n"
                + st("Name") + f": {user.first_name} {user.last_name or ''}\n"
                + st("ID") + f": <code>{user.id}</code>\n"
                + st("Link") + f": {link}\n"
                + st("Time") + f": {now}",
            )


# ================== REPLY KEYBOARD ==================
def main_reply_keyboard(user_id: int):
    rows = [
        [KeyboardButton(st("BAN ACCOUNT"))],
        [KeyboardButton(st("DEVELOPER")), KeyboardButton(st("SUPPORT"))],
    ]
    if user_id == OWNER_ID:
        rows.append([KeyboardButton(st("OWNER PANEL"))])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def confirm_inline_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(st("YES BAN"), callback_data="confirm_ban_yes")],
            [InlineKeyboardButton(st("CANCEL"), callback_data="confirm_ban_no")],
        ]
    )


# ================== START ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id != OWNER_ID and is_user_banned(user.id):
        await update.message.reply_text(
            st("You are banned from using this bot") + f"\n{st('Contact')} @{DEVELOPER_USERNAME}"
        )
        return

    await track_user(update, context)

    welcome_img = get_setting("welcome_image")
    caption = (
        st("Welcome") + f" {user.first_name}\n\n"
        + st("Your ID") + f": <code>{user.id}</code>\n"
        + st("Developer") + f": @{DEVELOPER_USERNAME}\n\n"
        + st("This bot is used for banning FF accounts")
    )

    kb = main_reply_keyboard(user.id)

    if welcome_img:
        try:
            await update.message.reply_photo(
                photo=welcome_img, caption=caption, reply_markup=kb, parse_mode="HTML"
            )
            return
        except Exception as e:
            logger.error(f"Welcome image failed: {e}")

    await update.message.reply_text(caption, reply_markup=kb, parse_mode="HTML")


# ================== BAN FLOW ==================
async def ban_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat_id
        user_id = query.from_user.id
    else:
        chat_id = update.message.chat_id
        user_id = update.effective_user.id

    if user_id != OWNER_ID and is_user_banned(user_id):
        await context.bot.send_message(
            chat_id=chat_id,
            text=st("You are banned from using this bot") + f"\n{st('Contact')} @{DEVELOPER_USERNAME}",
        )
        return

    await context.bot.send_message(chat_id=chat_id, text=st("Send your access token"))
    context.user_data["awaiting_token"] = True


async def handle_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text.strip()
    context.user_data["awaiting_token"] = False

    if not token:
        await update.message.reply_text(st("Invalid token, try again"))
        return

    context.user_data["target_token"] = token

    await update.message.reply_text(
        st("Are you 100 percent sure to ban account"),
        reply_markup=confirm_inline_keyboard(),
    )


async def confirm_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_ban_no":
        await query.edit_message_text(st("Ban cancelled"))
        context.user_data.pop("target_token", None)
        return

    user_id = query.from_user.id
    price = get_setting("ban_price", "0")

    if price and price != "0" and not is_user_approved(user_id):
        upi_id = get_setting("upi_id", "example@upi")
        holder = get_setting("holder_name", "Owner")
        try:
            qr_bio = generate_upi_qr(upi_id, float(price), holder)
            await query.edit_message_text(
                st("Payment Required") + "\n\n"
                + st("Amount") + f": {st(str(price))}\n"
                + st("UPI ID") + f": <code>{upi_id}</code>\n"
                + st("Holder") + f": {holder}",
                parse_mode="HTML",
            )
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=InputFile(qr_bio, filename="qr.png"),
                caption=st("Scan and pay") + f"\n{st('UPI')}: {upi_id}\n{st('Holder')}: {holder}",
            )
            kb = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton(st("CONFIRM PAYMENT"), callback_data="payment_done")],
                    [InlineKeyboardButton(st("CANCEL"), callback_data="payment_cancel")],
                ]
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=st("After paying click below"),
                reply_markup=kb,
            )
        except Exception as e:
            logger.error(f"QR failed: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id, text=st("Payment setup error")
            )
        return

    await execute_ban(query.message.chat_id, query.from_user.id, context)


async def execute_ban(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    token = context.user_data.get("target_token")
    if not token:
        await context.bot.send_message(chat_id=chat_id, text=st("Token missing, start again"))
        return

    api_url = f"{BAN_API_BASE}{token}&key={API_KEY}"
    success = False
    game_name = "Unknown"
    game_uid = "Unknown"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(api_url)
            logger.info(f"API {resp.status_code}: {resp.text[:300]}")
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
            chat_id=chat_id, text=st("Ban failed API error")
        )
        context.user_data.pop("target_token", None)
        return

    if success:
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
            st("Account Banned") + "\n\n"
            + f'<a href="{user_link}">{st("User")}</a> '
            + st("ID") + f": {user_id}\n"
            + st("Game Name") + f": {game_name}\n"
            + st("Game UID") + f": <code>{game_uid}</code>\n"
            + st("Time") + f": {now}",
        )

        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(st("BAN ANOTHER"), callback_data="ban_account_start")]]
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=st("Account Banned") + "\n\n"
            + st("Name") + f": {game_name}\n"
            + st("UID") + f": {game_uid}\n\n"
            + st("Developer") + f": @{DEVELOPER_USERNAME}",
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id, text=st("Ban failed, check token")
        )

    context.user_data.pop("target_token", None)


# ================== PAYMENT ==================
async def payment_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(st("Send payment screenshot now"))
    context.user_data["awaiting_screenshot"] = True


async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    user = update.effective_user
    context.user_data["awaiting_screenshot"] = False

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(st("APPROVE"), callback_data=f"approve_{user.id}")],
            [InlineKeyboardButton(st("DISAPPROVE"), callback_data=f"reject_{user.id}")],
        ]
    )
    await context.bot.send_photo(
        chat_id=OWNER_ID,
        photo=photo.file_id,
        caption=(
            st("Payment Screenshot") + "\n\n"
            + f"{user.first_name} (@{user.username or 'no_user'})\n"
            + st("ID") + f": {user.id}\n"
            + f"tg://user?id={user.id}"
        ),
        reply_markup=kb,
    )
    await update.message.reply_text(st("Wait for admin review"))


async def approve_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    action = parts[0]
    target = int(parts[1])

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if action == "approve":
        c.execute("UPDATE users SET is_approved=1 WHERE user_id=?", (target,))
        conn.commit()
        conn.close()
        try:
            await context.bot.send_message(
                chat_id=target, text=st("Now you have unlimited access")
            )
        except Exception as e:
            logger.error(f"Notify approve failed: {e}")
        await query.edit_message_caption(caption=st("Approved"))
    else:
        c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (target,))
        conn.commit()
        conn.close()
        try:
            await context.bot.send_message(
                chat_id=target,
                text=st("You are banned, contact") + f" @{DEVELOPER_USERNAME}",
            )
        except Exception as e:
            logger.error(f"Notify reject failed: {e}")
        await query.edit_message_caption(caption=st("Disapproved"))


# ================== OWNER PANEL ==================
async def show_owner_panel(chat_id, context, message_id=None):
    kb = [
        [InlineKeyboardButton(st("TOTAL USERS"), callback_data="owner_stats")],
        [InlineKeyboardButton(st("ALL BANNED IDS"), callback_data="owner_all_bans")],
        [InlineKeyboardButton(st("BAN USER BY ID"), callback_data="owner_ban_user")],
        [InlineKeyboardButton(st("UNBAN USER BY ID"), callback_data="owner_unban_user")],
        [InlineKeyboardButton(st("SET WELCOME IMAGE"), callback_data="owner_set_welcome")],
        [InlineKeyboardButton(st("SET BAN PRICE"), callback_data="owner_set_price")],
        [InlineKeyboardButton(st("SET UPI ID"), callback_data="owner_set_upi")],
        [InlineKeyboardButton(st("SET HOLDER NAME"), callback_data="owner_set_holder")],
    ]
    text = (
        st("Owner Panel") + "\n\n"
        + st("Ban Price") + f": {get_setting('ban_price', 'Not set')}\n"
        + st("UPI ID") + f": {get_setting('upi_id', 'Not set')}\n"
        + st("Holder") + f": {get_setting('holder_name', 'Not set')}"
    )
    markup = InlineKeyboardMarkup(kb)
    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text,
                reply_markup=markup, parse_mode="HTML",
            )
            return
        except Exception:
            pass
    await context.bot.send_message(
        chat_id=chat_id, text=text, reply_markup=markup, parse_mode="HTML"
    )


async def owner_panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await show_owner_panel(update.message.chat_id, context)


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
        await query.edit_message_text(st("Cancelled"))
    elif data == "payment_done":
        await payment_done(update, context)
    elif data == "payment_cancel":
        await query.edit_message_text(st("Payment cancelled"))
    elif data.startswith("approve_") or data.startswith("reject_"):
        if user_id == OWNER_ID:
            await approve_payment(update, context)
    elif data == "owner_panel":
        if user_id == OWNER_ID:
            await show_owner_panel(
                query.message.chat_id, context, message_id=query.message.message_id
            )
    elif data == "owner_stats":
        if user_id != OWNER_ID:
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users"); total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM bans"); bans = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE is_approved=1"); appr = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE is_banned=1"); banu = c.fetchone()[0]
        conn.close()
        await query.edit_message_text(
            st("Bot Stats") + "\n\n"
            + st("Total Users") + f": {total}\n"
            + st("Approved Users") + f": {appr}\n"
            + st("Banned Users") + f": {banu}\n"
            + st("Total Bans") + f": {bans}",
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
            await query.edit_message_text(st("No bans recorded"))
        else:
            txt = st("Recent Bans") + "\n\n"
            for i, r in enumerate(rows, 1):
                txt += f"{i}. {st('UID')}: {r[0]} | {st('Name')}: {r[1]} | {r[2]}\n"
            await query.edit_message_text(txt)
    elif data == "owner_set_welcome":
        if user_id != OWNER_ID: return
        await query.edit_message_text(st("Send welcome image photo"))
        context.user_data["owner_action"] = "set_welcome"
    elif data == "owner_set_price":
        if user_id != OWNER_ID: return
        await query.edit_message_text(st("Send ban price number"))
        context.user_data["owner_action"] = "set_price"
    elif data == "owner_set_upi":
        if user_id != OWNER_ID: return
        await query.edit_message_text(st("Send your UPI ID"))
        context.user_data["owner_action"] = "set_upi"
    elif data == "owner_set_holder":
        if user_id != OWNER_ID: return
        await query.edit_message_text(st("Send account holder name"))
        context.user_data["owner_action"] = "set_holder"
    elif data == "owner_ban_user":
        if user_id != OWNER_ID: return
        await query.edit_message_text(st("Send user ID to ban"))
        context.user_data["owner_action"] = "ban_user"
    elif data == "owner_unban_user":
        if user_id != OWNER_ID: return
        await query.edit_message_text(st("Send user ID to unban"))
        context.user_data["owner_action"] = "unban_user"


# ================== MESSAGE HANDLER ==================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message
    text = msg.text if msg.text else None
    photo = msg.photo if msg.photo else None

    # Reply keyboard buttons
    if text:
        t = text.strip().lower()
        if t in (st("BAN ACCOUNT").lower(), "ban account"):
            await ban_account_start(update, context)
            return
        if t in (st("DEVELOPER").lower(), "developer"):
            await msg.reply_text(
                f"{st('Developer')}: @{DEVELOPER_USERNAME}\n{DEVELOPER_LINK}"
            )
            return
        if t in (st("SUPPORT").lower(), "support"):
            await msg.reply_text(
                f"{st('Support')}: @{DEVELOPER_USERNAME}\n{DEVELOPER_LINK}"
            )
            return
        if t in (st("OWNER PANEL").lower(), "owner panel") and user_id == OWNER_ID:
            await show_owner_panel(msg.chat_id, context)
            return

    # Owner actions
    if user_id == OWNER_ID and context.user_data.get("owner_action"):
        action = context.user_data["owner_action"]
        context.user_data["owner_action"] = None
        if action == "set_welcome" and photo:
            set_setting("welcome_image", photo[-1].file_id)
            await msg.reply_text(st("Welcome image set"))
        elif action == "set_price" and text:
            try:
                float(text)
                set_setting("ban_price", text)
                await msg.reply_text(st("Ban price set to") + f" {text}")
            except ValueError:
                await msg.reply_text(st("Invalid number"))
        elif action == "set_upi" and text:
            set_setting("upi_id", text)
            await msg.reply_text(st("UPI ID set to") + f" {text}")
        elif action == "set_holder" and text:
            set_setting("holder_name", text)
            await msg.reply_text(st("Holder name set to") + f" {text}")
        elif action == "ban_user" and text:
            try:
                target = int(text)
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (target,))
                conn.commit(); conn.close()
                await msg.reply_text(st("User banned") + f" {target}")
            except ValueError:
                await msg.reply_text(st("Invalid ID"))
        elif action == "unban_user" and text:
            try:
                target = int(text)
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (target,))
                conn.commit(); conn.close()
                await msg.reply_text(st("User unbanned") + f" {target}")
            except ValueError:
                await msg.reply_text(st("Invalid ID"))
        return

    if context.user_data.get("awaiting_screenshot") and photo:
        await handle_screenshot(update, context)
        return

    if context.user_data.get("awaiting_token") and text:
        await handle_token(update, context)
        return


# ================== MAIN ==================
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing")
        return
    if not OWNER_ID:
        logger.error("OWNER_ID missing")
        return

    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("owner", owner_panel_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))

    logger.info("Bot starting polling")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
