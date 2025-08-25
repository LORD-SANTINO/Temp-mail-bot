import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import asyncio
import json
import os
from typing import Dict, Any, List

# Configuration
TOKEN = "YOUR_BOT_TOKEN_HERE"  # <-- REPLACE THIS WITH YOUR REAL BOT TOKEN
DATA_FILE = "user_sessions.json"

# Load user sessions from file
def load_user_sessions() -> Dict[int, Dict[str, Any]]:
    """Load user sessions from JSON file."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                # Convert string keys back to integers
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    return {}

# Save user sessions to file
def save_user_sessions():
    """Save user sessions to JSON file."""
    with open(DATA_FILE, 'w') as f:
        json.dump(user_sessions, f, indent=2)

# Load existing data on startup
user_sessions: Dict[int, Dict[str, Any]] = load_user_sessions()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message when the command /start is issued."""
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
    """Generate a new email and add it to the user's list of inboxes."""
    chat_id = update.effective_chat.id

    # Get a new email from 1secMail API
    api_url = "https://www.1secmail.com/api/v1/?action=genRandomMailbox&count=1"
    try:
        response = requests.get(api_url)
        new_email_addr = response.json()[0]
    except requests.exceptions.RequestException:
        await update.message.reply_text("❌ Sorry, the email service is currently down.")
        return

    # Initialize the user's entry if it doesn't exist
    if chat_id not in user_sessions:
        user_sessions[chat_id] = {'inboxes': []}

    # Get the next ID for the new inbox
    if user_sessions[chat_id]['inboxes']:
        next_id = max(inbox['id'] for inbox in user_sessions[chat_id]['inboxes']) + 1
    else:
        next_id = 1

    # Create the new inbox dictionary
    new_inbox = {
        'id': next_id,
        'email': new_email_addr,
        'seen_ids': []
    }

    # Append it to the user's list of inboxes
    user_sessions[chat_id]['inboxes'].append(new_inbox)
    
    # Save the updated data to file
    save_user_sessions()

    # Ensure a background job is running for global checks
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
    """List all of the user's active email addresses."""
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
    """Delete a specific email from the user's list."""
    chat_id = update.effective_chat.id
    args = context.args

    # Check if user provided an ID to delete
    if not args or not args[0].isdigit():
        await update.message.reply_text("❌ Usage: /delete_email <number>\nExample: /delete_email 2")
        return

    inbox_id_to_delete = int(args[0])

    if chat_id not in user_sessions:
        await update.message.reply_text("❌ You don't have any emails to delete.")
        return

    # Find the inbox with the matching ID
    inboxes_list = user_sessions[chat_id]['inboxes']
    for index, inbox in enumerate(inboxes_list):
        if inbox['id'] == inbox_id_to_delete:
            # Remove it from the list
            deleted_email = inboxes_list.pop(index)['email']
            
            # If no more inboxes, remove the user entry completely
            if not inboxes_list:
                del user_sessions[chat_id]
            
            # Save the updated data to file
            save_user_sessions()
            
            await update.message.reply_text(f"🗑️ Deleted email: `{deleted_email}`", parse_mode='Markdown')
            return

    # If the loop finished without finding the ID
    await update.message.reply_text(f"❌ Could not find an email with ID #{inbox_id_to_delete}.")

async def check_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Let the user choose which email inbox they want to check."""
    chat_id = update.effective_chat.id

    # Check if user has any emails
    if chat_id not in user_sessions or not user_sessions[chat_id]['inboxes']:
        await update.message.reply_text("❌ You don't have any active emails. Use /new_email to create one.")
        return

    user_inboxes = user_sessions[chat_id]['inboxes']

    # If user has only one email, check it directly without buttons
    if len(user_inboxes) == 1:
        email_to_check = user_inboxes[0]['email']
        await _check_single_inbox(update, context, email_to_check)
        return

    # If user has multiple emails, show buttons
    keyboard = []
    # Create a button for each email
    for inbox in user_inboxes:
        # Use the email as the callback_data so we know which one was clicked
        button = [InlineKeyboardButton(f"📧 {inbox['email']}", callback_data=f"check_{inbox['email']}")]
        keyboard.append(button)

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🔍 **Which inbox would you like to check?**",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def _check_single_inbox(update, context, email_address):
    """Helper function to check a specific email inbox and report results."""
    # Find which user and specific inbox this is for
    if hasattr(update, 'callback_query') and update.callback_query:
        chat_id = update.callback_query.message.chat.id
    else:
        chat_id = update.message.chat.id
        
    login, domain = email_address.split('@')
    
    # Find this specific inbox in the user's list
    user_inboxes = user_sessions[chat_id]['inboxes']
    target_inbox = None
    for inbox in user_inboxes:
        if inbox['email'] == email_address:
            target_inbox = inbox
            break
            
    if not target_inbox:
        # Fallback in case something goes wrong
        response_text = "❌ Error: Email not found in your list."
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(response_text)
        else:
            await update.message.reply_text(response_text)
        return

    seen_ids = target_inbox['seen_ids']
    inbox_url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
    
    try:
        response = requests.get(inbox_url)
        messages = response.json()
    except requests.exceptions.RequestException:
        response_text = "❌ Failed to connect to the email service."
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

    # Save the updated seen_ids to file
    save_user_sessions()

    if not new_messages:
        response_text = f"📭 No new messages in `{email_address}`."
    else:
        response_text = f"📨 Found {len(new_messages)} new message(s) in `{email_address}`!\n\n"
        # For simplicity, we just report the count. You could expand this to show details.
        
    # Update the message based on how it was called
    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(response_text, parse_mode='Markdown')
    else:
        await update.message.reply_text(response_text, parse_mode='Markdown')

async def inbox_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the inline button presses for checking specific inboxes."""
    query = update.callback_query
    await query.answer()  # Important to answer the callback query

    # The callback_data is formatted as "check_EMAIL_ADDRESS"
    if query.data.startswith("check_"):
        email_to_check = query.data[6:]  # Remove the "check_" prefix to get the email
        await _check_single_inbox(update, context, email_to_check)

async def global_check_inbox_job(context: ContextTypes.DEFAULT_TYPE):
    """A single global job that checks for new messages for ALL inboxes of ALL users."""
    bot = context.bot
    # Loop through all users
    for chat_id, user_data in user_sessions.items():
        # Loop through each inbox for this user
        for inbox in user_data['inboxes']:
            email = inbox['email']
            login, domain = email.split('@')
            seen_ids = inbox['seen_ids']

            # Check inbox for this specific email address
            inbox_url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
            try:
                response = requests.get(inbox_url)
                messages = response.json()
            except requests.exceptions.RequestException:
                continue  # Skip this inbox if the API call fails

            new_messages_found = False
            for msg in messages:
                if msg['id'] not in seen_ids:
                    # NEW MESSAGE FOUND!
                    new_messages_found = True
                    seen_ids.append(msg['id'])
                    read_url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={msg['id']}"
                    msg_detail = requests.get(read_url).json()

                    alert_text = f"📩 **New message to** `{email}`:\n"
                    alert_text += f"**From:** {msg_detail['from']}\n"
                    alert_text += f"**Subject:** {msg_detail['subject']}\n\n"
                    alert_text += f"**Message:**\n{msg_detail['textBody'][:500]}..." 

                    # Send the alert to the user
                    await bot.send_message(chat_id=chat_id, text=alert_text)
            
            # Save data if new messages were found
            if new_messages_found:
                save_user_sessions()

def main():
    """Start the bot."""
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_email", new_email))
    application.add_handler(CommandHandler("my_emails", my_emails))
    application.add_handler(CommandHandler("delete_email", delete_email))
    application.add_handler(CommandHandler("check_inbox", check_inbox))
    
    # Add the handler for inline button callbacks
    application.add_handler(CallbackQueryHandler(inbox_button_callback))

    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
