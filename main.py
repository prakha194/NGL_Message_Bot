import os
import asyncio
import logging
import aiohttp
import random
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# Configuration from environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

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
    conn.commit()
    conn.close()

# Rate limiting functions
def check_rate_limit(user_id):
    conn = sqlite3.connect('ngl_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT last_reset FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    if result:
        last_reset = datetime.fromisoformat(result[0])
        if datetime.now() - last_reset > timedelta(hours=24):
            cursor.execute('UPDATE users SET message_count = 0, last_reset = ? WHERE user_id = ?', 
                         (datetime.now(), user_id))
            conn.commit()
    
    cursor.execute('SELECT message_count FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    if not result:
        cursor.execute('INSERT INTO users (user_id, message_count) VALUES (?, ?)', (user_id, 0))
        conn.commit()
        current_count = 0
    else:
        current_count = result[0]
    
    conn.close()
    return current_count

def update_rate_limit(user_id, count):
    conn = sqlite3.connect('ngl_bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET message_count = message_count + ? WHERE user_id = ?', (count, user_id))
    conn.commit()
    conn.close()

# Generate message with Gemini API
async def generate_gemini_message(prompt="Generate a fun anonymous message"):
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "contents": [{
                    "parts": [{
                        "text": f"Generate a short, fun anonymous message for NGL. {prompt}. Keep it under 50 characters and make it casual."
                    }]
                }]
            }
            
            headers = {
                "Content-Type": "application/json"
            }
            
            url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
            
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return data['candidates'][0]['content']['parts'][0]['text'].strip()
                else:
                    return f"Fun message #{random.randint(1000,9999)}"
    except Exception as e:
        logging.error(f"Gemini API Error: {e}")
        return f"Random message {random.randint(1000,9999)}"

# Send message to NGL
async def send_ngl_message(ngl_link, message):
    try:
        username = ngl_link.replace('https://ngl.link/', '').split('?')[0]
        
        async with aiohttp.ClientSession() as session:
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
            
            async with session.post(
                "https://ngl.link/api/submit",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                return response.status == 200
    except Exception as e:
        logging.error(f"NGL Send Error: {e}")
        return False

# Admin notification
async def notify_admin(context: ContextTypes.DEFAULT_TYPE, message: str):
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=message)
    except Exception as e:
        logging.error(f"Admin notify error: {e}")

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
        logging.error(f"Database error: {e}")

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = """
🤖 NGL Message Bot

Commands:
/start - Show this welcome message
/send - Send messages to NGL link
/track - Track your sent messages

Features:
• Send messages to any NGL link
• Auto-generate messages with AI
• Custom messages support
• Rate limiting (8 messages/24 hours)
• Message tracking

Rate Limits:
• 4 messages per request
• 8 messages per 24 hours
• Admin: No limits
    """
    
    await update.message.reply_text(welcome_text)
    
    # Notify admin
    admin_msg = f"👤 New User:\nID: {user.id}\nUsername: @{user.username if user.username else 'N/A'}\nName: {user.first_name}"
    await notify_admin(context, admin_msg)

# Send command handler
async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        current_count = check_rate_limit(user_id)
        if current_count >= 8:
            await update.message.reply_text("❌ Rate limit exceeded! You can only send 8 messages per 24 hours.")
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
    
    if data == "enter_link":
        context.user_data['awaiting_link'] = True
        await query.edit_message_text("Please send me the NGL link (e.g., https://ngl.link/username)")
    
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
            [InlineKeyboardButton("1 Message", callback_data="count_1")],
            [InlineKeyboardButton("2 Messages", callback_data="count_2")],
            [InlineKeyboardButton("3 Messages", callback_data="count_3")],
            [InlineKeyboardButton("4 Messages", callback_data="count_4")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("How many AI messages to send?", reply_markup=reply_markup)
    
    elif data == "custom_message":
        context.user_data['message_type'] = 'custom'
        await query.edit_message_text("Please send your custom message (max 4 messages):")
        context.user_data['awaiting_custom'] = True
        context.user_data['custom_messages'] = []
    
    elif data.startswith("count_"):
        count = int(data.split("_")[1])
        context.user_data['message_count'] = count
        
        if context.user_data.get('message_type') == 'ai':
            messages = []
            for i in range(count):
                msg = await generate_gemini_message()
                messages.append(msg)
            
            context.user_data['messages'] = messages
            
            message_text = "\n".join([f"{i+1}. {msg}" for i, msg in enumerate(messages)])
            keyboard = [
                [InlineKeyboardButton("🔄 Regenerate All", callback_data="regenerate_all")],
                [InlineKeyboardButton("🚀 Send Messages", callback_data="send_messages")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"Generated messages:\n\n{message_text}", reply_markup=reply_markup)
    
    elif data == "regenerate_all":
        count = context.user_data.get('message_count', 1)
        messages = []
        for i in range(count):
            msg = await generate_gemini_message()
            messages.append(msg)
        
        context.user_data['messages'] = messages
        message_text = "\n".join([f"{i+1}. {msg}" for i, msg in enumerate(messages)])
        keyboard = [
            [InlineKeyboardButton("🔄 Regenerate All", callback_data="regenerate_all")],
            [InlineKeyboardButton("🚀 Send Messages", callback_data="send_messages")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"Regenerated messages:\n\n{message_text}", reply_markup=reply_markup)
    
    elif data == "send_messages":
        await send_messages_process(update, context)

# Handle text messages
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if context.user_data.get('awaiting_link'):
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
    
    elif context.user_data.get('awaiting_custom'):
        context.user_data['custom_messages'].append(text)
        remaining = 4 - len(context.user_data['custom_messages'])
        
        if remaining > 0:
            await update.message.reply_text(f"Message added! You can add {remaining} more messages or send now.")
        else:
            context.user_data['awaiting_custom'] = False
            context.user_data['messages'] = context.user_data['custom_messages']
            context.user_data['message_count'] = len(context.user_data['messages'])
            
            message_text = "\n".join([f"{i+1}. {msg}" for i, msg in enumerate(context.user_data['messages'])])
            keyboard = [[InlineKeyboardButton("🚀 Send Messages", callback_data="send_messages")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(f"Your messages:\n\n{message_text}", reply_markup=reply_markup)

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
        if current_count + len(messages) > 8:
            await query.edit_message_text("❌ Rate limit exceeded! You can only send 8 messages per 24 hours.")
            return
    
    success_count = 0
    failed_count = 0
    
    status_message = await query.edit_message_text("🔄 Sending messages...")
    
    for i, message in enumerate(messages):
        if i > 0:
            delay = random.uniform(2, 5)
            await asyncio.sleep(delay)
        
        success = await send_ngl_message(ngl_link, message)
        
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
    
    admin_msg = f"""
📨 New Message Batch:
User: @{query.from_user.username if query.from_user.username else 'N/A'} ({user_id})
Link: {ngl_link}
Success: {success_count}/{len(messages)}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    await notify_admin(context, admin_msg)

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

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Error: {context.error}")
    error_msg = f"❌ Bot Error:\n{context.error}"
    await notify_admin(context, error_msg)

async def main():
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("send", send_command))
    application.add_handler(CommandHandler("track", track_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_error_handler(error_handler)
    
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
