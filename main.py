import os
import time
import random
import sqlite3
import requests
import threading
import asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from flask import Flask

# Configuration from environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

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
        CREATE TABLE IF NOT EXISTS scheduled_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ngl_link TEXT,
            messages TEXT,
            scheduled_time TIMESTAMP,
            status TEXT DEFAULT 'scheduled',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

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
        if datetime.now() - last_reset > timedelta(hours=24):
            cursor.execute('UPDATE users SET message_count = 0, last_reset = ? WHERE user_id = ?', 
                         (datetime.now(), user_id))
            conn.commit()
            current_count = 0
        else:
            current_count = message_count
    else:
        cursor.execute('INSERT INTO users (user_id, message_count, last_reset) VALUES (?, ?, ?)', 
                     (user_id, 0, datetime.now()))
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

# Save scheduled message
def save_scheduled_message(user_id, ngl_link, messages, scheduled_time):
    try:
        conn = sqlite3.connect('ngl_bot.db')
        cursor = conn.cursor()
        messages_json = '\n'.join(messages)
        cursor.execute(
            'INSERT INTO scheduled_messages (user_id, ngl_link, messages, scheduled_time) VALUES (?, ?, ?, ?)',
            (user_id, ngl_link, messages_json, scheduled_time)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Save scheduled error: {e}")
        return False

# Get scheduled messages
def get_scheduled_messages():
    try:
        conn = sqlite3.connect('ngl_bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM scheduled_messages 
            WHERE status = 'scheduled' AND scheduled_time <= datetime('now')
        ''')
        messages = cursor.fetchall()
        conn.close()
        return messages
    except Exception as e:
        print(f"Get scheduled error: {e}")
        return []

# Update scheduled message status
def update_scheduled_status(schedule_id, status):
    try:
        conn = sqlite3.connect('ngl_bot.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE scheduled_messages SET status = ? WHERE id = ?',
            (status, schedule_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Update scheduled error: {e}")

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    welcome_text = """
🤖 NGL Message Bot

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
        welcome_text += "\n\n👑 Admin Commands:\n/scheduler - Schedule messages"
    
    await update.message.reply_text(welcome_text)

# Scheduler command (admin only)
async def scheduler_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ This command is for admin only!")
        return
    
    keyboard = [[InlineKeyboardButton("🔗 Enter NGL Link", callback_data="scheduler_enter_link")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📅 Schedule Messages - Enter NGL link:", reply_markup=reply_markup)

# Send command handler
async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        current_count = check_rate_limit(user_id)
        if current_count >= 30:
            await update.message.reply_text("❌ Daily limit exceeded! You can only send 30 messages per 24 hours.\n\nNeed help? Contact admin!")
            return
    
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
        context.user_data['flow_type'] = 'instant'
        await query.edit_message_text("Please send me the NGL link (e.g., https://ngl.link/username)")
    
    elif data == "scheduler_enter_link":
        context.user_data['awaiting_link'] = True
        context.user_data['flow_type'] = 'scheduler'
        await query.edit_message_text("📅 Schedule Messages\n\nPlease send NGL link (e.g., https://ngl.link/username)")
    
    elif data == "message_type":
        keyboard = [
            [InlineKeyboardButton("🤖 AI Generated", callback_data="ai_message")],
            [InlineKeyboardButton("✏️ Custom Message", callback_data="custom_message")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Choose message type:", reply_markup=reply_markup)
    
    elif data == "scheduler_message_type":
        keyboard = [
            [InlineKeyboardButton("🤖 AI Generated", callback_data="scheduler_ai_message")],
            [InlineKeyboardButton("✏️ Custom Message", callback_data="scheduler_custom_message")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📅 Choose message type for scheduling:", reply_markup=reply_markup)
    
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
    
    elif data == "scheduler_ai_message":
        context.user_data['message_type'] = 'ai'
        keyboard = [
            [InlineKeyboardButton("🇺🇸 English", callback_data="scheduler_lang_english")],
            [InlineKeyboardButton("🇮🇳 Hindi", callback_data="scheduler_lang_hindi")],
            [InlineKeyboardButton("🇳🇵 Nepali", callback_data="scheduler_lang_nepali")],
            [InlineKeyboardButton("🇷🇺 Russian", callback_data="scheduler_lang_russian")],
            [InlineKeyboardButton("🔀 Hinglish", callback_data="scheduler_lang_hinglish")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📅 Choose language for AI messages:", reply_markup=reply_markup)
    
    elif data.startswith("scheduler_lang_"):
        language = data.split("_")[2]
        context.user_data['language'] = language
        await query.edit_message_text("📅 How many AI messages to schedule?\n\nSend the number (e.g., 3, 5, 10, etc.):")
        context.user_data['awaiting_scheduler_count'] = True
    
    elif data == "custom_message":
        context.user_data['message_type'] = 'custom'
        keyboard = [
            [InlineKeyboardButton("1 Message", callback_data="custom_1")],
            [InlineKeyboardButton("2 Messages", callback_data="custom_2")],
            [InlineKeyboardButton("3 Messages", callback_data="custom_3")],
            [InlineKeyboardButton("4 Messages", callback_data="custom_4")],
            [InlineKeyboardButton("5 Messages", callback_data="custom_5")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("How many custom messages to send?", reply_markup=reply_markup)
    
    elif data == "scheduler_custom_message":
        context.user_data['message_type'] = 'custom'
        await query.edit_message_text("📅 How many custom messages to schedule?\n\nSend the number (e.g., 3, 5, 10, etc.):")
        context.user_data['awaiting_scheduler_count'] = True
    
    elif data.startswith("lang_"):
        language = data.split("_")[1]
        context.user_data['language'] = language
        
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

# Handle text messages
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # Scheduler count input
    if context.user_data.get('awaiting_scheduler_count'):
        try:
            count = int(text)
            context.user_data['message_count'] = count
            context.user_data['awaiting_scheduler_count'] = False
            
            if context.user_data.get('message_type') == 'ai':
                # Generate AI messages immediately after getting count
                language = context.user_data.get('language', 'english')
                messages = generate_gemini_message(language=language, count=count)
                context.user_data['messages'] = messages
                
                message_text = "\n".join([f"{i+1}. {msg}" for i, msg in enumerate(messages)])
                language_name = LANGUAGES.get(language, language)
                
                await update.message.reply_text(f"📅 AI Messages Generated ({language_name}):\n\n{message_text}\n\nSend schedule time (Format: YYYY-MM-DD HH:MM)\nExample: 2024-12-25 14:30")
                context.user_data['awaiting_schedule_time'] = True
            else:
                context.user_data['custom_messages'] = []
                context.user_data['awaiting_custom'] = True
                context.user_data['current_custom_index'] = 0
                await update.message.reply_text(f"📅 Please send custom message 1/{count}:")
        except ValueError:
            await update.message.reply_text("❌ Please send a valid number (e.g., 3, 5, 10):")
    
    # Schedule time input
    elif context.user_data.get('awaiting_schedule_time'):
        try:
            scheduled_time = datetime.strptime(text, '%Y-%m-%d %H:%M')
            if scheduled_time <= datetime.now():
                await update.message.reply_text("❌ Schedule time must be in future!\n\nSend time (Format: YYYY-MM-DD HH:MM)\nExample: 2024-12-25 14:30")
                return
            
            ngl_link = context.user_data.get('ngl_link')
            messages = context.user_data.get('messages', [])
            
            if save_scheduled_message(user_id, ngl_link, messages, scheduled_time):
                time_left = scheduled_time - datetime.now()
                hours_left = int(time_left.total_seconds() // 3600)
                minutes_left = int((time_left.total_seconds() % 3600) // 60)
                
                report_text = f"""
✅ Messages Scheduled Successfully!

📅 Schedule Report:
• Link: {ngl_link}
• Messages: {len(messages)}
• Scheduled Time: {scheduled_time.strftime('%Y-%m-%d %H:%M')}
• Time Left: {hours_left}h {minutes_left}m
• Status: ⏰ Scheduled

Messages will be sent automatically at the scheduled time.
"""
                await update.message.reply_text(report_text)
            else:
                await update.message.reply_text("❌ Failed to schedule messages!")
            
            context.user_data.clear()
        except ValueError:
            await update.message.reply_text("❌ Invalid time format!\n\nSend time (Format: YYYY-MM-DD HH:MM)\nExample: 2024-12-25 14:30")
    
    # Regular link input
    elif context.user_data.get('awaiting_link'):
        if text.startswith('https://ngl.link/'):
            context.user_data['ngl_link'] = text
            context.user_data['awaiting_link'] = False
            
            if context.user_data.get('flow_type') == 'scheduler':
                keyboard = [
                    [InlineKeyboardButton("🤖 AI Generated", callback_data="scheduler_ai_message")],
                    [InlineKeyboardButton("✏️ Custom Message", callback_data="scheduler_custom_message")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("📅 Choose message type for scheduling:", reply_markup=reply_markup)
            else:
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
            
            if context.user_data.get('flow_type') == 'scheduler':
                message_text = "\n".join([f"{i+1}. {msg}" for i, msg in enumerate(context.user_data['messages'])])
                await update.message.reply_text(f"📅 Your {len(context.user_data['messages'])} messages:\n\n{message_text}\n\nSend schedule time (Format: YYYY-MM-DD HH:MM)\nExample: 2024-12-25 14:30")
                context.user_data['awaiting_schedule_time'] = True
            else:
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
            await query.edit_message_text("❌ Daily limit exceeded! You can only send 30 messages per 24 hours.\n\nNeed help? Contact admin!")
            return
        elif current_count >= 20:
            await query.edit_message_text("⚠️ You've sent 20+ messages today. Slow down! You can send up to 30 messages per 24 hours.\n\nNeed help? Contact admin!")
    
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
        admin_msg = f"""
📨 Message Batch Completed:
User: @{query.from_user.username if query.from_user.username else 'N/A'} ({user_id})
Link: {ngl_link}
Success: {success_count}/{len(messages)}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        await notify_admin(context, admin_msg, user_id)

# Track command
async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('ngl_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT ngl_link, message_text, status, timestamp 
        FROM messages 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 10
    ''', (user_id,))
    
    messages = cursor.fetchall()
    conn.close()
    
    if not messages:
        await update.message.reply_text("📭 No messages sent yet. Use /send to start sending messages.")
        return
    
    track_text = "📊 Your Recent Messages:\n\n"
    
    for i, (link, text, status, timestamp) in enumerate(messages):
        status_icon = "✅" if status == "success" else "❌"
        time_str = datetime.fromisoformat(timestamp).strftime("%m/%d %H:%M")
        track_text += f"{status_icon} {time_str}\n"
        track_text += f"Link: {link}\n"
        track_text += f"Message: {text[:50]}...\n\n"
    
    await update.message.reply_text(track_text)

# Process scheduled messages
async def process_scheduled_messages(application):
    while True:
        try:
            scheduled_messages = get_scheduled_messages()
            for msg in scheduled_messages:
                msg_id, user_id, ngl_link, messages_text, scheduled_time, status, created_at = msg
                messages = messages_text.split('\n')
                
                # Send messages
                success_count = 0
                for i, message in enumerate(messages):
                    if i > 0:
                        time.sleep(random.uniform(2, 5))
                    success = send_ngl_message(ngl_link, message)
                    if success:
                        success_count += 1
                    track_message(user_id, ngl_link, message, "success" if success else "failed")
                
                # Update status
                update_scheduled_status(msg_id, 'completed')
                
                # Notify admin
                report_text = f"""
⏰ Scheduled Messages Sent:
• Link: {ngl_link}
• Messages: {len(messages)}
• Successful: {success_count}
• Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
                await application.bot.send_message(chat_id=ADMIN_ID, text=report_text)
            
            await asyncio.sleep(60)  # Check every minute
        except Exception as e:
            print(f"Scheduled messages error: {e}")
            await asyncio.sleep(60)

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    error_msg = f"❌ Bot Error:\n{context.error}"
    if update.effective_user:
        await notify_admin(context, error_msg, update.effective_user.id)
    else:
        await notify_admin(context, error_msg, 0)

async def start_scheduler(application):
    asyncio.create_task(process_scheduled_messages(application))

def main():
    init_db()
    
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("send", send_command))
    application.add_handler(CommandHandler("track", track_command))
    application.add_handler(CommandHandler("scheduler", scheduler_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_error_handler(error_handler)
    
    # Start scheduler
    application.run_polling()
    
    print("Bot is running...")

if __name__ == "__main__":
    main()