import os
import logging
import sqlite3
import httpx
import qrcode
from io import BytesIO
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- CONFIG ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID"))  # Aapka Telegram User ID
BAN_API_BASE = "https://jexarcodexacstoban.vercel.app/close?access_token="
API_KEY = "ANIXH"  # Aapne jo key di hai
DEVELOPER_USERNAME = "@SYNTHX_ERRORR"

# --- DATABASE SETUP (SQLite) ---
DB_PATH = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        link TEXT,
        first_seen TEXT,
        last_seen TEXT,
        is_approved INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS bans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        game_uid TEXT,
        game_name TEXT,
        banned_at TEXT,
        banned_by INTEGER
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
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
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# --- HELPER FUNCTIONS ---
async def notify_owner(context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Owner notify failed: {e}")

def generate_upi_qr(upi_id: str, amount: float, name: str = "Owner"):
    """Generates UPI QR code image and returns as BytesIO."""
    upi_url = f"upi://pay?pa={upi_id}&pn={name}&am={amount}&cu=INR"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(upi_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio

# --- USER TRACKING (Every interaction) ---
async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id == OWNER_ID:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    link = f"tg://user?id={user.id}"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user.id,))
    exists = c.fetchone()
    if exists:
        c.execute("UPDATE users SET last_seen=?, username=?, first_name=?, last_name=?, link=? WHERE user_id=?",
                  (now, user.username, user.first_name, user.last_name, link, user.id))
    else:
        c.execute("INSERT INTO users (user_id, username, first_name, last_name, link, first_seen, last_seen) VALUES (?,?,?,?,?,?,?)",
                  (user.id, user.username, user.first_name, user.last_name, link, now, now))
        # Notify Owner on FIRST start
        await notify_owner(context, f"🆕 <b>New User Started Bot</b>\n\n"
                                     f"👤 Name: {user.first_name} {user.last_name or ''}\n"
                                     f"🆔 ID: <code>{user.id}</code>\n"
                                     f"🔗 Link: {link}\n"
                                     f"⏰ Time: {now}")
    conn.commit()
    conn.close()

# --- BAN ACCOUNT FLOW ---
async def ban_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔑 <b>Send your Access Token</b>\n\n"
        "Please send the Access Token of the account you want to ban.\n"
        "⚠️ Make sure it is correct, otherwise the ban will fail.",
        parse_mode="HTML"
    )
    context.user_data["awaiting_token"] = True

async def handle_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_token"):
        return
    token = update.message.text.strip()
    context.user_data["awaiting_token"] = False
    context.user_data["target_token"] = token

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ YES, BAN", callback_data="confirm_ban_yes")],
        [InlineKeyboardButton("❌ CANCEL", callback_data="confirm_ban_no")]
    ])
    await update.message.reply_text(
        "⚠️ <b>Are you 100% sure to ban this account?</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

async def confirm_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_ban_no":
        await query.edit_message_text("❌ Ban cancelled.")
        return

    # Payment Check (if price is set)
    price = get_setting("ban_price")
    if price and price != "0":
        # Show QR for payment
        upi_id = get_setting("upi_id", "example@upi")
        holder = get_setting("holder_name", "Owner")
        qr_bio = generate_upi_qr(upi_id, float(price), holder)
        await query.edit_message_text(
            f"💰 <b>Payment Required</b>\n\n"
            f"Amount: ₹{price}\n"
            f"UPI ID: <code>{upi_id}</code>\n"
            f"Account Holder: {holder}\n\n"
            f"Scan the QR below, then click 'Confirm Payment'.",
            parse_mode="HTML"
        )
        await context.bot.send_photo(chat_id=query.message.chat_id, photo=InputFile(qr_bio, filename="qr.png"))
        # Then ask for confirmation
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm Payment", callback_data="payment_done")],
            [InlineKeyboardButton("❌ Cancel", callback_data="payment_cancel")]
        ])
        await context.bot.send_message(chat_id=query.message.chat_id, text="After paying, click below:", reply_markup=kb)
        return

    # If no price, proceed to ban directly
    await execute_ban(query, context)

async def execute_ban(query_or_update, context: ContextTypes.DEFAULT_TYPE):
    token = context.user_data.get("target_token")
    if not token:
        await context.bot.send_message(chat_id=query_or_update.message.chat_id, text="❌ Token missing. Start again.")
        return

    # Call the API
    api_url = f"{BAN_API_BASE}{token}&key={API_KEY}"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(api_url)
            resp.raise_for_status()
            # Assume API returns JSON with success or info
            data = resp.json()
            # Aapko API response structure ke hisaab se adjust karna padega
            # Yahan main maan raha hoon success field hai
            success = data.get("success", True)  # Default true for demo, adjust
            game_name = data.get("name", "Unknown")
            game_uid = data.get("uid", "Unknown")
        except Exception as e:
            logging.error(f"Ban API error: {e}")
            await context.bot.send_message(chat_id=query_or_update.message.chat_id, text=f"❌ Ban failed: API error.\n{str(e)}")
            return

    if success:
        # Save to DB
        user_id = query_or_update.from_user.id if hasattr(query_or_update, 'from_user') else None
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO bans (user_id, game_uid, game_name, banned_at, banned_by) VALUES (?,?,?,?,?)",
                  (user_id, game_uid, game_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
        conn.commit()
        conn.close()

        # Notify Owner
        user_link = f"tg://user?id={user_id}"
        await notify_owner(context,
            f"🚫 <b>Account Banned</b>\n\n"
            f"👤 User: <a href='{user_link}'>User</a> (ID: {user_id})\n"
            f"🎮 Game Name: {game_name}\n"
            f"🆔 Game UID: <code>{game_uid}</code>\n"
            f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔨 Ban Another", callback_data="ban_again")]])
        await context.bot.send_message(
            chat_id=query_or_update.message.chat_id,
            text=f"✅ <b>Account Banned!</b>\n\n"
                 f"🎮 Name: {game_name}\n"
                 f"🆔 UID: {game_uid}\n\n"
                 f"👨‍💻 Developer: {DEVELOPER_USERNAME}",
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await context.bot.send_message(chat_id=query_or_update.message.chat_id, text="❌ Ban failed. Check token.")

# --- PAYMENT SCREENSHOT FLOW ---
async def payment_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📸 Please send the payment screenshot now.")
    context.user_data["awaiting_screenshot"] = True

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_screenshot"):
        return
    photo = update.message.photo[-1]
    user = update.effective_user
    context.user_data["awaiting_screenshot"] = False

    # Forward to owner with approve/reject buttons
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}")],
        [InlineKeyboardButton("❌ Disapprove", callback_data=f"reject_{user.id}")]
    ])
    await context.bot.send_photo(
        chat_id=OWNER_ID,
        photo=photo.file_id,
        caption=f"💰 Payment Screenshot from {user.first_name} (ID: {user.id})\n"
                f"User Link: tg://user?id={user.id}",
        reply_markup=kb
    )
    await update.message.reply_text("⏳ Wait for admin review. You will be notified.")

async def approve_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    action = data[0]
    target_user_id = int(data[1])

    if action == "approve":
        # Grant access
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET is_approved=1 WHERE user_id=?", (target_user_id,))
        conn.commit()
        conn.close()
        await context.bot.send_message(chat_id=target_user_id, text="✅ Now you have unlimited access!")
        await query.edit_message_caption(caption="✅ Approved.")
        # Proceed to ban if token exists? (Optional)
    else:
        await context.bot.send_message(chat_id=target_user_id, text=f"❌ You are banned. Contact {DEVELOPER_USERNAME}")
        await query.edit_message_caption(caption="❌ Disapproved.")

# --- OWNER PANEL ---
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    kb = [
        [InlineKeyboardButton("👥 Total Users", callback_data="owner_stats")],
        [InlineKeyboardButton("🚫 Ban User (by ID)", callback_data="owner_ban_user")],
        [InlineKeyboardButton("✅ Unban User (by ID)", callback_data="owner_unban_user")],
        [InlineKeyboardButton("📋 All Banned IDs", callback_data="owner_all_bans")],
        [InlineKeyboardButton("🖼️ Set Welcome Image", callback_data="owner_set_welcome")],
        [InlineKeyboardButton("💰 Set Ban Price", callback_data="owner_set_price")],
        [InlineKeyboardButton("🏦 Set UPI ID", callback_data="owner_set_upi")],
        [InlineKeyboardButton("👤 Set Holder Name", callback_data="owner_set_holder")],
    ]
    await update.message.reply_text("👑 <b>Owner Panel</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# --- START COMMAND ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await track_user(update, context)
    user = update.effective_user

    # Welcome Image
    welcome_img = get_setting("welcome_image")
    text = f"👋 Welcome {user.first_name}!\n\n"
    text += f"🆔 Your ID: <code>{user.id}</code>\n"
    text += f"👨‍💻 Developer: {DEVELOPER_USERNAME}\n"
    text += "⚔️ This bot is used for banning FF accounts."

    kb = [
        [InlineKeyboardButton("🔨 BAN ACCOUNT", callback_data="ban_account_start")],
        [InlineKeyboardButton("👨‍💻 Developer", url=f"https://t.me/{DEVELOPER_USERNAME.replace('@','')}")],
    ]
    if user.id == OWNER_ID:
        kb.append([InlineKeyboardButton("👑 Owner Panel", callback_data="owner_panel")])

    reply_markup = InlineKeyboardMarkup(kb)

    if welcome_img:
        try:
            await update.message.reply_photo(photo=welcome_img, caption=text, reply_markup=reply_markup, parse_mode="HTML")
            return
        except:
            pass
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")

# --- CALLBACK ROUTER ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

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
        await approve_payment(update, context)
    elif data == "owner_panel":
        # Show owner panel inline
        kb = [
            [InlineKeyboardButton("👥 Total Users", callback_data="owner_stats")],
            [InlineKeyboardButton("🚫 Ban User", callback_data="owner_ban_user")],
            [InlineKeyboardButton("✅ Unban User", callback_data="owner_unban_user")],
            [InlineKeyboardButton("📋 All Bans", callback_data="owner_all_bans")],
            [InlineKeyboardButton("🖼️ Welcome Image", callback_data="owner_set_welcome")],
            [InlineKeyboardButton("💰 Set Price", callback_data="owner_set_price")],
            [InlineKeyboardButton("🏦 UPI ID", callback_data="owner_set_upi")],
            [InlineKeyboardButton("👤 Holder Name", callback_data="owner_set_holder")],
        ]
        await query.edit_message_text("👑 <b>Owner Panel</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    elif data == "owner_stats":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM bans")
        bans = c.fetchone()[0]
        conn.close()
        await query.edit_message_text(f"👥 Total Users: {total}\n🚫 Total Bans: {bans}")
    elif data == "owner_all_bans":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT game_uid, game_name, banned_at FROM bans ORDER BY id DESC LIMIT 20")
        rows = c.fetchall()
        conn.close()
        if not rows:
            await query.edit_message_text("No bans recorded.")
        else:
            txt = "📋 <b>Recent Bans</b>\n\n"
            for r in rows:
                txt += f"🆔 {r[0]} | 🎮 {r[1]} | ⏰ {r[2]}\n"
            await query.edit_message_text(txt, parse_mode="HTML")
    # Owner settings prompts (simplified)
    elif data == "owner_set_welcome":
        await query.edit_message_text("Send the photo you want as welcome image.")
        context.user_data["owner_action"] = "set_welcome"
    elif data == "owner_set_price":
        await query.edit_message_text("Send the ban price (number only, e.g., 50).")
        context.user_data["owner_action"] = "set_price"
    elif data == "owner_set_upi":
        await query.edit_message_text("Send your UPI ID (e.g., name@upi).")
        context.user_data["owner_action"] = "set_upi"
    elif data == "owner_set_holder":
        await query.edit_message_text("Send account holder name.")
        context.user_data["owner_action"] = "set_holder"
    elif data == "owner_ban_user":
        await query.edit_message_text("Send the User ID to ban from using this bot.")
        context.user_data["owner_action"] = "ban_user"
    elif data == "owner_unban_user":
        await query.edit_message_text("Send the User ID to unban.")
        context.user_data["owner_action"] = "unban_user"

# --- MESSAGE HANDLER (Handles all text/photo based on state) ---
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
            set_setting("ban_price", text)
            await update.message.reply_text(f"✅ Ban price set to ₹{text}.")
        elif action == "set_upi" and text:
            set_setting("upi_id", text)
            await update.message.reply_text(f"✅ UPI ID set to {text}.")
        elif action == "set_holder" and text:
            set_setting("holder_name", text)
            await update.message.reply_text(f"✅ Holder name set to {text}.")
        elif action == "ban_user" and text:
            # Ban user by setting is_approved = 0 (or a banned flag)
            try:
                target = int(text)
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET is_approved=0 WHERE user_id=?", (target,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ User {target} banned from using bot.")
            except:
                await update.message.reply_text("❌ Invalid ID.")
        elif action == "unban_user" and text:
            try:
                target = int(text)
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET is_approved=1 WHERE user_id=?", (target,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"✅ User {target} unbanned.")
            except:
                await update.message.reply_text("❌ Invalid ID.")
        return

    # Screenshot handling
    if context.user_data.get("awaiting_screenshot") and photo:
        await handle_screenshot(update, context)
        return

    # Token handling
    if context.user_data.get("awaiting_token") and text:
        await handle_token(update, context)
        return

# --- MAIN ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("owner", owner_panel))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))

    logging.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
