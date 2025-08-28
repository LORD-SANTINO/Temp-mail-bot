import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import json
import os
import logging
import mailbox
import random
import string
from typing import Dict, Any


logging.basicConfig(level=logging.DEBUG)

# Inside your _check_single_inbox: 
logging.debug(f"Checking Maildrop inbox for mailbox: {mailbox}")
try:
    resp = requests.get(f"{MAILDROP_API}/mailbox/{mailbox}")
    resp.raise_for_status()
    logging.debug(f"Maildrop response code: {resp.status_code}")
    logging.debug(f"Maildrop response content: {resp.text}")
    messages = resp.json().get("messages", [])
except Exception as e:
    logging.error(f"Error fetching Maildrop mailbox: {e}")


TOKEN = "8327606596:AAHbJyzdnbNY3rWMfhy7e86S1wqihQxy0JQ"  # Your Telegram Bot Token here
DATA_FILE = "user_sessions.json"
MAILDROP_API = "https://api.maildrop.cc/v1"

# Load sessions
def load_user_sessions() -> Dict[int, Dict[str, Any]]:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception:
            return {}
    return {}

def generate_mailbox_name(length=8):
    mailbox = ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
    logging.debug(f"Generated mailbox: {mailbox}")
    return mailbox

# Save sessions
def save_user_sessions():
    with open(DATA_FILE, 'w') as f:
        json.dump(user_sessions, f, indent=2)

user_sessions: Dict[int, Dict[str, Any]] = load_user_sessions()

# Utility: Generate random mailbox name
def generate_mailbox_name(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **Welcome to Maildrop TempMail Bot!**\n\n"
        "Generate disposable emails via Maildrop service.\n\n"
        "**Commands:**\n"
        "/new_email - Generate a new temporary email\n"
        "/my_emails - List your active emails\n"
        "/delete_email - Remove an email address\n"
        "/check_inbox - Check for new messages",
        parse_mode="Markdown"
    )

async def new_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    mailbox = generate_mailbox_name()
    email_address = f"{mailbox}@maildrop.cc"

    if chat_id not in user_sessions:
        user_sessions[chat_id] = {"inboxes": []}

    next_id = max((inbox['id'] for inbox in user_sessions[chat_id]['inboxes']), default=0) + 1

    user_sessions[chat_id]["inboxes"].append({
        "id": next_id,
        "email": email_address,
        "mailbox": mailbox,
        "seen_ids": []
    })

    save_user_sessions()

    await update.message.reply_text(
        f"✅ **New email created!**\n**Address:** `{email_address}`\n\n"
        f"Use /my_emails to see all your addresses.",
        parse_mode="Markdown"
    )

async def my_emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in user_sessions or not user_sessions[chat_id]["inboxes"]:
        await update.message.reply_text("❌ You don't have any active emails. Use /new_email to create one.")
        return

    inboxes = user_sessions[chat_id]["inboxes"]
    text = "📧 **Your Active Emails:**\n\n"
    for inbox in inboxes:
        text += f"{inbox['id']}. `{inbox['email']}`\n"
    text += "\nUse `/delete_email <number>` to remove one."
    await update.message.reply_text(text, parse_mode="Markdown")

async def delete_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args or not args[0].isdigit():
        await update.message.reply_text("❌ Usage: /delete_email <number>\nExample: /delete_email 2")
        return

    inbox_id_to_delete = int(args[0])

    if chat_id not in user_sessions or not user_sessions[chat_id]["inboxes"]:
        await update.message.reply_text("❌ You don't have any emails to delete.")
        return

    inboxes = user_sessions[chat_id]["inboxes"]
    for i, inbox in enumerate(inboxes):
        if inbox["id"] == inbox_id_to_delete:
            removed = inboxes.pop(i)
            if not inboxes:
                del user_sessions[chat_id]

            save_user_sessions()
            await update.message.reply_text(f"🗑️ Deleted email: `{removed['email']}`", parse_mode="Markdown")
            return

    await update.message.reply_text(f"❌ Could not find an email with ID #{inbox_id_to_delete}.")

async def check_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_sessions or not user_sessions[chat_id]["inboxes"]:
        await update.message.reply_text("❌ You don't have any active emails. Use /new_email to create one.")
        return

    inboxes = user_sessions[chat_id]["inboxes"]
    if len(inboxes) == 1:
        await check_single_inbox(update, context, inboxes[0]["mailbox"])
        return

    keyboard = [
        [InlineKeyboardButton(f"📧 {inbox['email']}", callback_data=f"check_{inbox['mailbox']}")]
        for inbox in inboxes
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔍 **Which inbox would you like to check?**",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def check_single_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE, mailbox: str):
    chat_id = update.effective_chat.id if hasattr(update, "effective_chat") else update.message.chat.id
    if hasattr(update, "callback_query") and update.callback_query:
        chat_id = update.callback_query.message.chat.id

    inboxes = user_sessions.get(chat_id, {}).get("inboxes", [])
    target = next((i for i in inboxes if i["mailbox"] == mailbox), None)
    if not target:
        msg = "❌ Email not found in your list."
        if hasattr(update, "callback_query") and update.callback_query:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    seen_ids = target["seen_ids"]
    try:
        resp = requests.get(f"{MAILDROP_API}/mailbox/{mailbox}")
        resp.raise_for_status()
        messages = resp.json().get("messages", [])
    except requests.RequestException:
        msg = "❌ Failed to connect to Maildrop service."
        if hasattr(update, "callback_query") and update.callback_query:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    new_msgs = [m for m in messages if m["id"] not in seen_ids]
    for m in new_msgs:
        seen_ids.append(m["id"])
    save_user_sessions()

    if not new_msgs:
        msg = f"📭 No new messages in `{target['email']}`."
    else:
        msg = f"📨 Found {len(new_msgs)} new message(s) in `{target['email']}:`\n\n"
        for m in new_msgs:
            sender = m.get("from", "unknown")
            subject = m.get("subject", "(no subject)")
            msg += f"• **From:** {sender}\n  **Subject:** {subject}\n\n"

    if hasattr(update, "callback_query") and update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")

async def inbox_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("check_"):
        mailbox = query.data[len("check_") :]
        await check_single_inbox(update, context, mailbox)

def main():
    application = Application.builder().token(TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_email", new_email))
    application.add_handler(CommandHandler("my_emails", my_emails))
    application.add_handler(CommandHandler("delete_email", delete_email))
    application.add_handler(CommandHandler("check_inbox", check_inbox))
    application.add_handler(CallbackQueryHandler(inbox_button_callback, pattern=r'^check_.*'))

    # Start polling
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
