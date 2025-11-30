import os
import time
import random
import sqlite3
import requests
import threading
import asyncio
from datetime import datetime, timedelta
import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from flask import Flask

# Configuration from environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# Group and Channel IDs for membership check
GROUP_1_ID = "@KiddingARENA"  # Replace with your group 1 username
CHANNEL_ID = "@premiumlinkers"  # Replace with your channel username

# Set your timezone
TIMEZONE = pytz.timezone('Asia/Kolkata')

# Language mapping
LANGUAGES = {
    'english': 'English',
    'hindi': 'Hindi', 
    'nepali': 'Nepali',
    'russian': 'Russian',
    'hinglish': 'Hinglish'
}

# Flask app for port
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 NGL Telegram Bot is Running!"

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False)

# Initialize database
def init_db():
    conn = sqlite3.connect('ngl_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            message_count INTEGER DEFAULT 0,
            last_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ngl_link TEXT,
            message_text TEXT,
            status TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Get current time with timezone
def get_current_time():
    return datetime.now(TIMEZONE)

# Track bot users
def track_bot_user(user_id, username, first_name):
    try:
        conn = sqlite3.connect('ngl_bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO bot_users (user_id, username, first_name) 
            VALUES (?, ?, ?)
        ''', (user_id, username, first_name))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Track user error: {e}")

# Get all bot users for broadcast
def get_all_bot_users():
    try:
        conn = sqlite3.connect('ngl_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM bot_users')
        users = [row[0] for row in cursor.fetchall()]
        conn.close()
        return users
    except Exception as e:
        print(f"Get users error: {e}")
        return []

# Rate limiting functions
def check_rate_limit(user_id):
    conn = sqlite3.connect('ngl_bot.db')
    cursor = conn.cursor()

    cursor.execute('SELECT last_reset, message_count FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()

    if result:
        last_reset = datetime.fromisoformat(result[0])
        message_count = result[1]

        # Reset if 24 hours passed
        if get_current_time() - last_reset > timedelta(hours=24):
            cursor.execute('UPDATE users SET message_count = 0, last_reset = ? WHERE user_id = ?', 
                         (get_current_time(), user_id))
            conn.commit()
            current_count = 0
        else:
            current_count = message_count
    else:
        cursor.execute('INSERT INTO users (user_id, message_count, last_reset) VALUES (?, ?, ?)', 
                     (user_id, 0, get_current_time()))
        conn.commit()
        current_count = 0

    conn.close()
    return current_count

def update_rate_limit(user_id, count):
    conn = sqlite3.connect('ngl_bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET message_count = message_count + ? WHERE user_id = ?', (count, user_id))
    conn.commit()
    conn.close()

# Generate message with Gemini API
def generate_gemini_message(language="english", count=1):
    try:
        language_prompts = {
            'english': 'Generate short, fun anonymous messages in English only.',
            'hindi': 'Generate short, fun anonymous messages in Hindi only.',
            'nepali': 'Generate short, fun anonymous messages in Nepali only.', 
            'russian': 'Generate short, fun anonymous messages in Russian only.',
            'hinglish': 'Generate short, fun anonymous messages in Hinglish only.'
        }

        base_prompt = language_prompts.get(language, language_prompts['english'])

        url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"{base_prompt} Generate {count} different messages. Keep them under 50 characters and make them casual."
                }]
            }]
        }

        headers = {
            "Content-Type": "application/json"
        }

        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            full_text = data['candidates'][0]['content']['parts'][0]['text'].strip()
            # Split the response into individual messages
            messages = [msg.strip() for msg in full_text.split('\n') if msg.strip()]
            # If we got fewer messages than requested, generate the rest
            while len(messages) < count:
                messages.append(f"Fun message #{random.randint(1000,9999)}")
            return messages[:count]
        else:
            return [f"Fun message #{random.randint(1000,9999)}" for _ in range(count)]
    except Exception as e:
        return [f"Random message {random.randint(1000,9999)}" for _ in range(count)]

# Send message to NGL
def send_ngl_message(ngl_link, message):
    try:
        username = ngl_link.replace('https://ngl.link/', '').split('?')[0]

        payload = {
            "username": username,
            "question": message,
            "deviceId": f"web_{random.randint(100000,999999)}",
            "gameSlug": "",
            "referrer": ""
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Content-Type": "application/json",
            "Origin": "https://ngl.link",
            "Referer": f"https://ngl.link/{username}"
        }

        response = requests.post(
            "https://ngl.link/api/submit",
            json=payload,
            headers=headers,
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        return False

# Admin notification (only for non-admin users)
async def notify_admin(context: ContextTypes.DEFAULT_TYPE, message: str, user_id: int):
    try:
        if user_id != ADMIN_ID:  # Only notify if not admin
            await context.bot.send_message(chat_id=ADMIN_ID, text=message)
    except Exception as e:
        print(f"Admin notify error: {e}")

# Track message in database
def track_message(user_id, ngl_link, message_text, status):
    try:
        conn = sqlite3.connect('ngl_bot.db')
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO messages (user_id, ngl_link, message_text, status) VALUES (?, ?, ?, ?)',
            (user_id, ngl_link, message_text, status)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database error: {e}")

# Check if user is member of groups and channel
async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        # Check group 1 membership
        member_group1 = await context.bot.get_chat_member(GROUP_1_ID, user_id)
        is_member_group1 = member_group1.status in ['member', 'administrator', 'creator']
        
        # Check group 2 membership
        member_group2 = await context.bot.get_chat_member(GROUP_2_ID, user_id)
        is_member_group2 = member_group2.status in ['member', 'administrator', 'creator']
        
        # Check channel membership
        member_channel = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        is_member_channel = member_channel.status in ['member', 'administrator', 'creator']
        
        if is_member_group1 and is_member_group2 and is_member_channel:
            await update.message.reply_text("✅ You are a member of all required groups and channel! You can now use the bot.")
        else:
            missing = []
            if not is_member_group1:
                missing.append(f"Group 1: {GROUP_1_ID}")
            if not is_member_group2:
                missing.append(f"Group 2: {GROUP_2_ID}")
            if not is_member_channel:
                missing.append(f"Channel: {CHANNEL_ID}")
            
            await update.message.reply_text(
                f"❌ Please join the following to use the bot:\n\n" +
                "\n".join(missing) +
                f"\n\nAfter joining, click 'Check Now' again."
            )
            
    except Exception as e:
        await update.message.reply_text("❌ Error checking membership. Please try again later.")

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Track user in database
    track_bot_user(user_id, username, first_name)
    
    current_time = get_current_time()
    welcome_text = f"""
🤖 NGL Message Bot

🕐 Current Time: {current_time.strftime('%Y/%m/%d-%I:%M-%p')}

Commands:
/start - Show this welcome message
/send - Send messages to NGL link
/track - Track your sent messages

Features:
• Send messages to any NGL link
• Auto-generate messages with AI (5 languages)
• Custom messages support
• Message tracking

Need help? Contact admin!
"""

    if user_id == ADMIN_ID:
        welcome_text += "\n\n👑 Admin Commands:\n/broadcast - Broadcast message to all users"

    await update.message.reply_text(welcome_text)
    
    # Show membership check buttons for all users
    keyboard = [
        [InlineKeyboardButton("🔗 Group 1", url=f"https://t.me/{GROUP_1_ID[1:]}")],
        [InlineKeyboardButton("🔗 Group 2", url=f"https://t.me/{GROUP_2_ID[1:]}")],
        [InlineKeyboardButton("🔗 Channel", url=f"https://t.me/{CHANNEL_ID[1:]}")],
        [InlineKeyboardButton("✅ Check Now", callback_data="check_membership")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📋 Please join our groups and channel to use the bot:\n\n" +
        f"• Group 1: {GROUP_1_ID}\n" +
        f"• Group 2: {GROUP_2_ID}\n" +
        f"• Channel: {CHANNEL_ID}\n\n" +
        "After joining, click 'Check Now' to verify.",
        reply_markup=reply_markup
    )

# Broadcast command (admin only)
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ This command is for admin only!")
        return

    keyboard = [
        [InlineKeyboardButton("📝 Text Message", callback_data="broadcast_text")],
        [InlineKeyboardButton("🖼️ Photo", callback_data="broadcast_photo")],
        [InlineKeyboardButton("📝 + 🖼️ Both", callback_data="broadcast_both")],
        [InlineKeyboardButton("↩️ Forward Message", callback_data="broadcast_forward")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📢 Choose broadcast type:", reply_markup=reply_markup)

# Handle broadcast callbacks
async def handle_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    if user_id != ADMIN_ID:
        await query.edit_message_text("❌ This command is for admin only!")
        return

    if data == "broadcast_text":
        context.user_data['broadcast_type'] = 'text'
        await query.edit_message_text("📝 Please send the text message to broadcast:")
        
    elif data == "broadcast_photo":
        context.user_data['broadcast_type'] = 'photo'
        await query.edit_message_text("🖼️ Please send the photo with caption (if any):")
        
    elif data == "broadcast_both":
        context.user_data['broadcast_type'] = 'both'
        await query.edit_message_text("📝 Please send the photo with caption:")
        
    elif data == "broadcast_forward":
        context.user_data['broadcast_type'] = 'forward'
        await query.edit_message_text("↩️ Please forward the message you want to broadcast:")

# Send broadcast to all users
async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, broadcast_type, content=None):
    try:
        users = get_all_bot_users()
        success_count = 0
        failed_count = 0
        
        await update.message.reply_text(f"📢 Starting broadcast to {len(users)} users...")
        
        for user_id in users:
            try:
                if broadcast_type == 'text':
                    await context.bot.send_message(chat_id=user_id, text=content)
                elif broadcast_type == 'photo':
                    await context.bot.send_photo(chat_id=user_id, photo=update.message.photo[-1].file_id, caption=content)
                elif broadcast_type == 'both':
                    await context.bot.send_photo(chat_id=user_id, photo=update.message.photo[-1].file_id, caption=content)
                elif broadcast_type == 'forward':
                    await context.bot.forward_message(chat_id=user_id, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
                
                success_count += 1
                await asyncio.sleep(0.1)  # Small delay to avoid rate limits
                
            except Exception as e:
                failed_count += 1
                print(f"Failed to send to {user_id}: {e}")
        
        await update.message.reply_text(
            f"✅ Broadcast completed!\n\n" +
            f"• Successful: {success_count}\n" +
            f"• Failed: {failed_count}\n" +
            f"• Total: {len(users)}"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Broadcast failed: {e}")

# Send command handler
async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        current_count = check_rate_limit(user_id)
        remaining = 30 - current_count
        if current_count >= 30:
            # Get time remaining until reset
            conn = sqlite3.connect('ngl_bot.db')
            cursor = conn.cursor()
            cursor.execute('SELECT last_reset FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            conn.close()

            if result:
                last_reset = datetime.fromisoformat(result[0])
                time_passed = get_current_time() - last_reset
                time_remaining = timedelta(hours=24) - time_passed
                hours_left = int(time_remaining.total_seconds() // 3600)
                minutes_left = int((time_remaining.total_seconds() % 3600) // 60)

                await update.message.reply_text(f"❌ Daily limit exceeded! You can only send 30 messages per 24 hours.\n\n⏰ Time remaining: {hours_left}h {minutes_left}m\n\nNeed help? Contact admin!")
            else:
                await update.message.reply_text("❌ Daily limit exceeded! You can only send 30 messages per 24 hours.\n\nNeed help? Contact admin!")
            return
        else:
            await update.message.reply_text(f"📊 You have {remaining} messages remaining today.")

    keyboard = [[InlineKeyboardButton("🔗 Enter NGL Link", callback_data="enter_link")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Click below to start sending messages:", reply_markup=reply_markup)

# Handle callback queries
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    # Regular send flow
    if data == "enter_link":
        context.user_data['awaiting_link'] = True
        await query.edit_message_text("Please send me the NGL link (e.g., https://ngl.link/username)")

    elif data == "check_membership":
        await check_membership(update, context)

    elif data == "message_type":
        keyboard = [
            [InlineKeyboardButton("🤖 AI Generated", callback_data="ai_message")],
            [InlineKeyboardButton("✏️ Custom Message", callback_data="custom_message")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Choose message type:", reply_markup=reply_markup)

    elif data == "ai_message":
        context.user_data['message_type'] = 'ai'
        keyboard = [
            [InlineKeyboardButton("🇺🇸 English", callback_data="lang_english")],
            [InlineKeyboardButton("🇮🇳 Hindi", callback_data="lang_hindi")],
            [InlineKeyboardButton("🇳🇵 Nepali", callback_data="lang_nepali")],
            [InlineKeyboardButton("🇷🇺 Russian", callback_data="lang_russian")],
            [InlineKeyboardButton("🔀 Hinglish", callback_data="lang_hinglish")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Choose language for AI messages:", reply_markup=reply_markup)

    elif data.startswith("lang_"):
        language = data.split("_")[1]
        context.user_data['language'] = language

        if user_id == ADMIN_ID:
            await query.edit_message_text("📝 How many AI messages to send?\n\nSend the number (1-200):")
            context.user_data['awaiting_count'] = True
        else:
            keyboard = [
                [InlineKeyboardButton("1 Message", callback_data="count_1")],
                [InlineKeyboardButton("2 Messages", callback_data="count_2")],
                [InlineKeyboardButton("3 Messages", callback_data="count_3")],
                [InlineKeyboardButton("4 Messages", callback_data="count_4")],
                [InlineKeyboardButton("5 Messages", callback_data="count_5")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            language_name = LANGUAGES.get(language, language)
            await query.edit_message_text(f"Selected: {language_name}\nHow many messages to send?", reply_markup=reply_markup)

    elif data == "custom_message":
        context.user_data['message_type'] = 'custom'
        if user_id == ADMIN_ID:
            await query.edit_message_text("📝 How many custom messages to send?\n\nSend the number (1-200):")
            context.user_data['awaiting_count'] = True
        else:
            keyboard = [
                [InlineKeyboardButton("1 Message", callback_data="custom_1")],
                [InlineKeyboardButton("2 Messages", callback_data="custom_2")],
                [InlineKeyboardButton("3 Messages", callback_data="custom_3")],
                [InlineKeyboardButton("4 Messages", callback_data="custom_4")],
                [InlineKeyboardButton("5 Messages", callback_data="custom_5")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("How many custom messages to send?", reply_markup=reply_markup)

    elif data.startswith("custom_"):
        count = int(data.split("_")[1])
        context.user_data['message_count'] = count
        context.user_data['custom_messages'] = []
        context.user_data['awaiting_custom'] = True
        context.user_data['current_custom_index'] = 0

        await query.edit_message_text(f"Please send your custom message 1/{count}:")

    elif data.startswith("count_"):
        count = int(data.split("_")[1])
        context.user_data['message_count'] = count

        if context.user_data.get('message_type') == 'ai':
            language = context.user_data.get('language', 'english')
            messages = generate_gemini_message(language=language, count=count)
            context.user_data['messages'] = messages

            # Forward AI messages to admin (only if not admin)
            if user_id != ADMIN_ID:
                admin_ai_msg = f"""
🤖 AI Messages Generated:
User: @{query.from_user.username if query.from_user.username else 'N/A'} ({user_id})
Language: {language}
Count: {count}
"""
                for i, msg in enumerate(messages):
                    admin_ai_msg += f"\n{i+1}. {msg}"

                await notify_admin(context, admin_ai_msg, user_id)

            message_text = "\n".join([f"{i+1}. {msg}" for i, msg in enumerate(messages)])
            language_name = LANGUAGES.get(language, language)

            keyboard = [
                [InlineKeyboardButton("🔄 Regenerate All", callback_data="regenerate_all")],
                [InlineKeyboardButton("🚀 Send Messages", callback_data="send_messages")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"Language: {language_name}\n\nGenerated messages:\n\n{message_text}", reply_markup=reply_markup)

    elif data == "regenerate_all":
        count = context.user_data.get('message_count', 1)
        language = context.user_data.get('language', 'english')
        messages = generate_gemini_message(language=language, count=count)
        context.user_data['messages'] = messages

        # Forward regenerated messages to admin (only if not admin)
        if user_id != ADMIN_ID:
            admin_regenerate_msg = f"""
🔄 AI Messages Regenerated:
User: @{query.from_user.username if query.from_user.username else 'N/A'} ({query.from_user.id})
Language: {language}
Count: {count}
"""
            for i, msg in enumerate(messages):
                admin_regenerate_msg += f"\n{i+1}. {msg}"

            await notify_admin(context, admin_regenerate_msg, user_id)

        message_text = "\n".join([f"{i+1}. {msg}" for i, msg in enumerate(messages)])
        language_name = LANGUAGES.get(language, language)
        keyboard = [
            [InlineKeyboardButton("🔄 Regenerate All", callback_data="regenerate_all")],
            [InlineKeyboardButton("🚀 Send Messages", callback_data="send_messages")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"Language: {language_name}\n\nRegenerated messages:\n\n{message_text}", reply_markup=reply_markup)

    elif data == "send_messages":
        await send_messages_process(update, context)

    # Handle broadcast callbacks
    elif data.startswith("broadcast_"):
        await handle_broadcast_callback(update, context)

# Handle text messages
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # Handle broadcast messages
    if context.user_data.get('broadcast_type'):
        broadcast_type = context.user_data['broadcast_type']
        
        if broadcast_type == 'text':
            await send_broadcast(update, context, 'text', text)
        elif broadcast_type in ['photo', 'both'] and update.message.photo:
            caption = text if text else None
            await send_broadcast(update, context, broadcast_type, caption)
        elif broadcast_type == 'forward' and update.message.forward_from_chat:
            await send_broadcast(update, context, 'forward')
        else:
            await update.message.reply_text("❌ Please send the correct content type.")
        
        context.user_data.clear()
        return

    # Admin custom count input
    if context.user_data.get('awaiting_count') and user_id == ADMIN_ID:
        try:
            count = int(text)
            if count < 1 or count > 200:
                await update.message.reply_text("❌ Please enter a number between 1 and 200:")
                return
                
            context.user_data['message_count'] = count
            context.user_data['awaiting_count'] = False

            if context.user_data.get('message_type') == 'ai':
                language = context.user_data.get('language', 'english')
                messages = generate_gemini_message(language=language, count=count)
                context.user_data['messages'] = messages

                message_text = "\n".join([f"{i+1}. {msg}" for i, msg in enumerate(messages)])
                language_name = LANGUAGES.get(language, language)

                keyboard = [
                    [InlineKeyboardButton("🔄 Regenerate All", callback_data="regenerate_all")],
                    [InlineKeyboardButton("🚀 Send Messages", callback_data="send_messages")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(f"Language: {language_name}\n\nGenerated messages:\n\n{message_text}", reply_markup=reply_markup)
            else:
                context.user_data['custom_messages'] = []
                context.user_data['awaiting_custom'] = True
                context.user_data['current_custom_index'] = 0
                await update.message.reply_text(f"Please send your custom message 1/{count}:")
        except ValueError:
            await update.message.reply_text("❌ Please send a valid number (1-200):")

    # Regular link input
    elif context.user_data.get('awaiting_link'):
        if text.startswith('https://ngl.link/'):
            context.user_data['ngl_link'] = text
            context.user_data['awaiting_link'] = False

            keyboard = [
                [InlineKeyboardButton("🤖 AI Generated", callback_data="ai_message")],
                [InlineKeyboardButton("✏️ Custom Message", callback_data="custom_message")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Great! Now choose message type:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("❌ Invalid NGL link. Please send a valid link starting with https://ngl.link/")

    # Custom messages input
    elif context.user_data.get('awaiting_custom'):
        # Forward custom message to admin (only if not admin)
        if user_id != ADMIN_ID:
            admin_custom_msg = f"""
📝 Custom Message from User:
User: @{update.effective_user.username if update.effective_user.username else 'N/A'} ({user_id})
Message {context.user_data['current_custom_index'] + 1}/{context.user_data['message_count']}:
{text}
"""
            await notify_admin(context, admin_custom_msg, user_id)

        context.user_data['custom_messages'].append(text)
        context.user_data['current_custom_index'] += 1

        remaining = context.user_data['message_count'] - len(context.user_data['custom_messages'])

        if remaining > 0:
            await update.message.reply_text(f"✅ Message {len(context.user_data['custom_messages'])}/{context.user_data['message_count']} added!\n\nSend next message ({remaining} remaining):")
        else:
            context.user_data['awaiting_custom'] = False
            context.user_data['messages'] = context.user_data['custom_messages']

            message_text = "\n".join([f"{i+1}. {msg}" for i, msg in enumerate(context.user_data['messages'])])
            keyboard = [[InlineKeyboardButton("🚀 Send Messages", callback_data="send_messages")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(f"Your {len(context.user_data['messages'])} messages:\n\n{message_text}", reply_markup=reply_markup)

# Send messages process
async def send_messages_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    ngl_link = context.user_data.get('ngl_link')
    messages = context.user_data.get('messages', [])

    if not ngl_link or not messages:
        await query.edit_message_text("❌ Error: Missing data")
        return

    if user_id != ADMIN_ID:
        current_count = check_rate_limit(user_id)
        if current_count + len(messages) > 30:
            # Get time remaining until reset
            conn = sqlite3.connect('ngl_bot.db')
            cursor = conn.cursor()
            cursor.execute('SELECT last_reset FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            conn.close()

            if result:
                last_reset = datetime.fromisoformat(result[0])
                time_passed = get_current_time() - last_reset
                time_remaining = timedelta(hours=24) - time_passed
                hours_left = int(time_remaining.total_seconds() // 3600)
                minutes_left = int((time_remaining.total_seconds() % 3600) // 60)

                await query.edit_message_text(f"❌ Daily limit exceeded! You can only send 30 messages per 24 hours.\n\n⏰ Time remaining: {hours_left}h {minutes_left}m\n\nNeed help? Contact admin!")
            else:
                await query.edit_message_text("❌ Daily limit exceeded! You can only send 30 messages per 24 hours.\n\nNeed help? Contact admin!")
            return
        elif current_count >= 20:
            remaining = 30 - current_count
            await query.edit_message_text(f"⚠️ You've sent {current_count} messages today. You have {remaining} messages remaining.\n\nSlow down! You can send up to 30 messages per 24 hours.\n\nNeed help? Contact admin!")

    success_count = 0
    failed_count = 0

    status_message = await query.edit_message_text("🔄 Sending messages...")

    for i, message in enumerate(messages):
        if i > 0:
            time.sleep(random.uniform(2, 5))

        success = send_ngl_message(ngl_link, message)

        status = "success" if success else "failed"
        track_message(user_id, ngl_link, message, status)

        if success:
            success_count += 1
        else:
            failed_count += 1

        await status_message.edit_text(f"🔄 Sending... ({i+1}/{len(messages)})")

    if user_id != ADMIN_ID:
        update_rate_limit(user_id, len(messages))

    result_text = f"""
✅ Messages Sent Complete!

📊 Results:
• Successful: {success_count}
• Failed: {failed_count}
• Total: {len(messages)}

Use /track to see detailed status.
"""

    await status_message.edit_text(result_text)

    # Notify admin only if not admin user
    if user_id != ADMIN_ID:
        current_time = get_current_time()
        admin_msg = f"""
📨 Message Batch Completed:
User: @{query.from_user.username if query.from_user.username else 'N/A'} ({user_id})
Link: {ngl_link}
Success: {success_count}/{len(messages)}
Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}
"""
        await notify_admin(context, admin_msg, user_id)

# Track command
async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_time = get_current_time()

    conn = sqlite3.connect('ngl_bot.db')
    cursor = conn.cursor()

    # Get sent messages
    cursor.execute('''
        SELECT ngl_link, message_text, status, timestamp 
        FROM messages 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 10
    ''', (user_id,))

    sent_messages = cursor.fetchall()
    conn.close()

    track_text = f"🕐 Current Time: {current_time.strftime('%Y/%m/%d-%I:%M-%p')}\n\n"

    # Show sent messages
    if sent_messages:
        track_text += "📊 Recent Sent Messages:\n\n"
        for i, (link, text, status, timestamp) in enumerate(sent_messages):
            status_icon = "✅" if status == "success" else "❌"
            time_str = datetime.fromisoformat(timestamp).astimezone(TIMEZONE).strftime("%m/%d %H:%M")
            track_text += f"{status_icon} {time_str}\n"
            track_text += f"Link: {link}\n"
            track_text += f"Message: {text[:50]}...\n\n"
    else:
        track_text += "📭 No messages sent yet. Use /send to start sending messages."

    await update.message.reply_text(track_text)

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        error_msg = f"❌ Bot Error:\n{context.error}"
        user_id = update.effective_user.id if update and update.effective_user else "Unknown"
        await notify_admin(context, error_msg, user_id)
    except Exception as e:
        print(f"Error handler failed: {e}")

def main():
    init_db()

    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("send", send_command))
    application.add_handler(CommandHandler("track", track_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_text))
    application.add_handler(MessageHandler(filters.FORWARDED, handle_text))
    application.add_error_handler(error_handler)

    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()