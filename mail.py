import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import asyncio
import json
import os
from typing import Dict, Any, List

# Configuration
TOKEN = "8327606596:AAHbJyzdnbNY3rWMfhy7e86S1wqihQxy0JQ"  # <-- REPLACE THIS WITH YOUR REAL BOT TOKEN
TEMP_MAIL_API_KEY = "YOUR_TEMP_MAIL_API_KEY"  # <-- Put your Temp Mail API key here
DATA_FILE = "user_sessions.json"

HEADERS = {"X-API-Key": TEMP_MAIL_API_KEY}
BASE_URL = "https://api.temp-mail.io/v1"

# Load user sessions from file
def load_user_sessions() -> Dict[int, Dict[str, Any]]:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    return {}

# Save user sessions to file
def save_user_sessions():
    with open(DATA_FILE, 'w') as f:
        json.dump(user_sessions, f, indent=2)

# Load existing data on startup
user_sessions: Dict[int, Dict[str, Any]] = load_user_sessions()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **Welcome to TempMail Bot!**\n\n"
        "Generate multiple disposable emails to avoid spam.\n\n"
        "**Commands:**\n"
        "/new_email - Generate a new temporary email\n"
        "/my_emails - List your active emails\n"
        "/delete_email - Remove an email address\n"
        "/check_inbox - Check for new messages",
        parse_mode='Markdown'
    )

async def new_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    api_url = f"{BASE_URL}/emails"

    try:
        response = requests.post(api_url, headers=HEADERS)
        response.raise_for_status()
        new_email_addr = response.json()['email']
    except requests.RequestException:
        await update.message.reply_text("❌ Sorry, the Temp Mail service is currently down.")
        return

    if chat_id not in user_sessions:
        user_sessions[chat_id] = {'inboxes': []}

    if user_sessions[chat_id]['inboxes']:
        next_id = max(inbox['id'] for inbox in user_sessions[chat_id]['inboxes']) + 1
    else:
        next_id = 1

    new_inbox = {
        'id': next_id,
        'email': new_email_addr,
        'seen_ids': []
    }

    user_sessions[chat_id]['inboxes'].append(new_inbox)
    save_user_sessions()

    if 'global_inbox_job' not in context.bot_data:
        context.bot_data['global_inbox_job'] = context.job_queue.run_repeating(
            global_check_inbox_job, interval=30, first=10
        )

    await update.message.reply_text(
        f"✅ **New email created!**\n**Address:** `{new_email_addr}`\n\n"
        f"It has been added to your list. Use /my_emails to see all your addresses.",
        parse_mode='Markdown'
    )

async def my_emails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_sessions or not user_sessions[chat_id]['inboxes']:
        await update.message.reply_text("❌ You don't have any active emails. Use /new_email to create one.")
        return

    inbox_list = user_sessions[chat_id]['inboxes']
    message_text = "📧 **Your Active Emails:**\n\n"
    for inbox in inbox_list:
        message_text += f"{inbox['id']}. `{inbox['email']}`\n"

    message_text += "\nUse `/delete_email <number>` to remove one."
    await update.message.reply_text(message_text, parse_mode='Markdown')

async def delete_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args or not args[0].isdigit():
        await update.message.reply_text("❌ Usage: /delete_email <number>\nExample: /delete_email 2")
        return

    inbox_id_to_delete = int(args[0])

    if chat_id not in user_sessions:
        await update.message.reply_text("❌ You don't have any emails to delete.")
        return

    inboxes_list = user_sessions[chat_id]['inboxes']
    for index, inbox in enumerate(inboxes_list):
        if inbox['id'] == inbox_id_to_delete:
            deleted_email = inboxes_list.pop(index)['email']
            if not inboxes_list:
                del user_sessions[chat_id]
            save_user_sessions()
            await update.message.reply_text(f"🗑️ Deleted email: `{deleted_email}`", parse_mode='Markdown')
            return

    await update.message.reply_text(f"❌ Could not find an email with ID #{inbox_id_to_delete}.")

async def check_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in user_sessions or not user_sessions[chat_id]['inboxes']:
        await update.message.reply_text("❌ You don't have any active emails. Use /new_email to create one.")
        return

    user_inboxes = user_sessions[chat_id]['inboxes']

    if len(user_inboxes) == 1:
        email_to_check = user_inboxes[0]['email']
        await _check_single_inbox(update, context, email_to_check)
        return

    keyboard = []
    for inbox in user_inboxes:
        button = [InlineKeyboardButton(f"📧 {inbox['email']}", callback_data=f"check_{inbox['email']}")]
        keyboard.append(button)

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🔍 **Which inbox would you like to check?**",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def _check_single_inbox(update, context, email_address):
    if hasattr(update, 'callback_query') and update.callback_query:
        chat_id = update.callback_query.message.chat.id
    else:
        chat_id = update.message.chat.id

    # Find user's inbox
    user_inboxes = user_sessions[chat_id]['inboxes']
    target_inbox = None
    for inbox in user_inboxes:
        if inbox['email'] == email_address:
            target_inbox = inbox
            break

    if not target_inbox:
        response_text = "❌ Error: Email not found in your list."
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(response_text)
        else:
            await update.message.reply_text(response_text)
        return

    seen_ids = target_inbox['seen_ids']
    inbox_url = f"{BASE_URL}/emails/{email_address}/messages"
    try:
        response = requests.get(inbox_url, headers=HEADERS)
        response.raise_for_status()
        messages = response.json().get('messages', [])
    except requests.RequestException:
        response_text = "❌ Failed to connect to the Temp Mail service."
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(response_text)
        else:
            await update.message.reply_text(response_text)
        return

    new_messages = []
    for msg in messages:
        if msg['id'] not in seen_ids:
            new_messages.append(msg)
            seen_ids.append(msg['id'])

    save_user_sessions()

    if not new_messages:
        response_text = f"📭 No new messages in `{email_address}`."
    else:
        response_text = f"📨 Found {len(new_messages)} new message(s) in `{email_address}`!\n\n"
        # Optionally, show subjects of new messages
        for msg in new_messages:
            response_text += f"• **From:** {msg.get('from', 'unknown')}\n  **Subject:** {msg.get('subject', '(no subject)')}\n\n"

    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(response_text, parse_mode='Markdown')
    else:
        await update.message.reply_text(response_text, parse_mode='Markdown')

async def inbox_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("check_"):
        email_to_check = query.data[6:]
        await _check_single_inbox(update, context, email_to_check)

async def global_check_inbox_job(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    for chat_id, user_data in user_sessions.items():
        for inbox in user_data['inboxes']:
            email = inbox['email']
            seen_ids = inbox['seen_ids']

            inbox_url = f"{BASE_URL}/emails/{email}/messages"
            try:
                response = requests.get(inbox_url, headers=HEADERS)
                response.raise_for_status()
                messages = response.json().get('messages', [])
            except requests.RequestException:
                continue

            new_messages_found = False

            for msg in messages:
                if msg['id'] not in seen_ids:
                    new_messages_found = True
                    seen_ids.append(msg['id'])
                    message_id = msg['id']
                    msg_detail_url = f"{BASE_URL}/messages/{message_id}"
                    try:
                        msg_detail = requests.get(msg_detail_url, headers=HEADERS).json()
                    except:
                        continue

                    alert_text = (f"📩 **New message to** `{email}`:\n"
                                  f"**From:** {msg_detail.get('from', 'unknown')}\n"
                                  f"**Subject:** {msg_detail.get('subject', '(no subject)')}\n\n"
                                  f"**Message:**\n{msg_detail.get('text', '')[:500]}...")

                    await bot.send_message(chat_id=chat_id, text=alert_text)

            if new_messages_found:
                save_user_sessions()

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
