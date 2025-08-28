import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import json
import os
from typing import Dict, Any

# Configuration
TOKEN = "8327606596:AAHbJyzdnbNY3rWMfhy7e86S1wqihQxy0JQ"  # <-- REPLACE WITH YOUR BOT TOKEN
DATA_FILE = "user_sessions.json"

MAILDROP_API = "https://api.maildrop.cc/v1"

# Load/save user session helpers
def load_user_sessions() -> Dict[int, Dict[str, Any]]:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except:
            return {}
    return {}

def save_user_sessions():
    with open(DATA_FILE, 'w') as f:
        json.dump(user_sessions, f, indent=2)

user_sessions: Dict[int, Dict[str, Any]] = load_user_sessions()

import random, string
def generate_mailbox():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **Welcome to Maildrop TempMail Bot!**\n\n"
        "Generate disposable emails via Maildrop service.\n\n"
        "**Commands:**\n"
        "/new_email - Generate a new disposable email\n"
        "/my_emails - List your emails\n"
        "/delete_email - Delete an email\n"
        "/check_inbox - Check for new messages",
        parse_mode='Markdown'
    )

async def new_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    mailbox = generate_mailbox()
    email_addr = f"{mailbox}@maildrop.cc"

    if chat_id not in user_sessions:
        user_sessions[chat_id] = {'inboxes': []}

    next_id = max([inbox['id'] for inbox in user_sessions[chat_id]['inboxes']], default=0) + 1

    user_sessions[chat_id]['inboxes'].append({
        'id': next_id,
        'email': email_addr,
        'mailbox': mailbox,
        'seen_ids': []
    })

    save_user_sessions()

    await update.message.reply_text(
        f"✅ **New email created!**\n**Address:** `{email_addr}`\nUse /my_emails to see your emails.",
        parse_mode='Markdown'
    )

async def my_emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_sessions or not user_sessions[chat_id]['inboxes']:
        await update.message.reply_text("❌ No active emails. Use /new_email to create one.")
        return

    message = "📧 **Your Active Emails:**\n\n"
    for inbox in user_sessions[chat_id]['inboxes']:
        message += f"{inbox['id']}. `{inbox['email']}`\n"
    message += "\nUse `/delete_email <number>` to delete one."
    await update.message.reply_text(message, parse_mode='Markdown')

async def delete_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args or not args[0].isdigit():
        await update.message.reply_text("❌ Usage: /delete_email <number>\nExample: /delete_email 2")
        return

    inbox_id = int(args[0])
    if chat_id not in user_sessions:
        await update.message.reply_text("❌ No emails to delete.")
        return

    inboxes = user_sessions[chat_id]['inboxes']
    for i, inbox in enumerate(inboxes):
        if inbox['id'] == inbox_id:
            deleted_email = inboxes.pop(i)['email']
            if not inboxes:
                del user_sessions[chat_id]
            save_user_sessions()
            await update.message.reply_text(f"🗑️ Deleted email: `{deleted_email}`", parse_mode='Markdown')
            return

    await update.message.reply_text(f"❌ Email with ID #{inbox_id} not found.")

async def check_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_sessions or not user_sessions[chat_id]['inboxes']:
        await update.message.reply_text("❌ No active emails. Use /new_email to create one.")
        return

    inboxes = user_sessions[chat_id]['inboxes']
    if len(inboxes) == 1:
        await _check_single_inbox(update, context, inboxes[0]['mailbox'])
        return

    keyboard = [
        [InlineKeyboardButton(f"📧 {inbox['email']}", callback_data=f"check_{inbox['mailbox']}")]
        for inbox in inboxes
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔍 **Select the inbox to check:**", reply_markup=reply_markup, parse_mode='Markdown'
    )

async def _check_single_inbox(update, context, mailbox):
    chat_id = update.effective_chat.id if hasattr(update, 'effective_chat') else update.message.chat.id
    if hasattr(update, 'callback_query') and update.callback_query:
        chat_id = update.callback_query.message.chat.id

    user_inboxes = user_sessions.get(chat_id, {}).get('inboxes', [])
    target_inbox = next((i for i in user_inboxes if i['mailbox'] == mailbox), None)
    if not target_inbox:
        response = "❌ Email not found in your list."
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(response)
        else:
            await update.message.reply_text(response)
        return

    seen_ids = target_inbox['seen_ids']
    inbox_url = f"{MAILDROP_API}/mailbox/{mailbox}"
    try:
        response = requests.get(inbox_url)
        response.raise_for_status()
        messages = response.json().get('messages', [])
    except requests.RequestException:
        resp = "❌ Failed to connect to Maildrop."
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(resp)
        else:
            await update.message.reply_text(resp)
        return

    new_msgs = [m for m in messages if m['id'] not in seen_ids]
    for m in new_msgs:
        seen_ids.append(m['id'])

    save_user_sessions()

    if not new_msgs:
        response_text = f"📭 No new messages in `{target_inbox['email']}`."
    else:
        response_text = f"📨 Found {len(new_msgs)} new message(s) in `{target_inbox['email']}`!\n\n"
        for msg in new_msgs:
            from_ = msg.get('from', 'unknown')
            subject = msg.get('subject', '(no subject)')
            response_text += f"• **From:** {from_}\n  **Subject:** {subject}\n\n"

    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(response_text, parse_mode='Markdown')
    else:
        await update.message.reply_text(response_text, parse_mode='Markdown')

async def inbox_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("check_"):
        mailbox = query.data[6:]
        await _check_single_inbox(update, context, mailbox)

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_email", new_email))
    application.add_handler(CommandHandler("my_emails", my_emails))
    application.add_handler(CommandHandler("delete_email", delete_email))
    application.add_handler(CommandHandler("check_inbox", check_inbox))
    application.add_handler(CallbackQueryHandler(inbox_button_callback))
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
