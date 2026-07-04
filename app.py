import os
import logging
import random
import string
import json
from datetime import datetime
from flask import Flask, request, jsonify, redirect, render_template_string
import requests
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# ============= ENVIRONMENT VARIABLES =============

# FIX: Hardcode port - Railway will map it correctly
PORT = 5000

# Required: Get Telegram Token
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN is required!")
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

# Get Base URL - Try multiple sources
BASE_URL = os.environ.get('BASE_URL')
if not BASE_URL:
    # Try Railway's public domain
    railway_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
    if railway_domain:
        BASE_URL = f"https://{railway_domain}"
    else:
        # Fallback to localhost
        BASE_URL = f"http://localhost:{PORT}"

# Other variables
MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/')
DATABASE_NAME = os.environ.get('DATABASE_NAME', 'shortlink_bot')
BOT_NAME = os.environ.get('BOT_NAME', "John's Shortlink Bot")
BOT_USERNAME = os.environ.get('BOT_USERNAME', 'john_shortlink_bot')
BOT_OWNER = os.environ.get('BOT_OWNER', '@john')

# Telegram API
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"{BASE_URL}/webhook"

logger.info(f"🚀 Configuration loaded:")
logger.info(f"   PORT: {PORT}")
logger.info(f"   BASE_URL: {BASE_URL}")
logger.info(f"   WEBHOOK_URL: {WEBHOOK_URL}")

# ============= IN-MEMORY STORAGE (Fallback) =============
in_memory_links = {}
in_memory_users = {}

# ============= MONGODB CONNECTION (Optional) =============
mongo_client = None
links_collection = None
users_collection = None

try:
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
    
    logger.info("Attempting to connect to MongoDB...")
    client = MongoClient(
        MONGODB_URI,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=5000
    )
    client.admin.command('ping')
    mongo_client = client
    db = mongo_client[DATABASE_NAME]
    links_collection = db['links']
    users_collection = db['users']
    
    try:
        links_collection.create_index('short_code', unique=True)
        links_collection.create_index('user_id')
        users_collection.create_index('user_id', unique=True)
        logger.info("✅ MongoDB indexes created")
    except Exception as e:
        logger.warning(f"⚠️ Index creation skipped: {e}")
    
    logger.info("✅ Connected to MongoDB successfully")
except ImportError:
    logger.warning("⚠️ pymongo not installed, using in-memory storage only")
except Exception as e:
    logger.warning(f"⚠️ MongoDB error: {e}")
    logger.warning("⚠️ Using in-memory storage as fallback")

# ============= HELPER FUNCTIONS =============

def generate_short_code(length=6):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def is_valid_url(url):
    if not url:
        return False
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    try:
        result = urlparse(url)
        if not result.scheme or not result.netloc:
            return False
        if '.' not in result.netloc:
            return False
        return True
    except:
        return False

def normalize_url(url):
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url

def save_link(short_code, original_url, user_id, custom=False):
    link_data = {
        'short_code': short_code,
        'original_url': original_url,
        'user_id': str(user_id),
        'created_at': datetime.utcnow().isoformat(),
        'clicks': 0,
        'is_active': True,
        'is_custom': custom
    }
    
    try:
        if links_collection is not None:
            links_collection.insert_one(link_data)
            logger.info(f"✅ Link saved in MongoDB: {short_code}")
        else:
            in_memory_links[short_code] = link_data
            logger.info(f"✅ Link saved in memory: {short_code}")
        return link_data
    except Exception as e:
        logger.error(f"❌ Failed to save link: {e}")
        try:
            in_memory_links[short_code] = link_data
            logger.info(f"✅ Link saved in memory (fallback): {short_code}")
            return link_data
        except:
            return None

def get_link(short_code):
    try:
        if links_collection is not None:
            link = links_collection.find_one({'short_code': short_code, 'is_active': True})
            if link:
                if '_id' in link:
                    link['_id'] = str(link['_id'])
                return link
        if short_code in in_memory_links:
            return in_memory_links[short_code]
    except Exception as e:
        logger.error(f"❌ Failed to retrieve link: {e}")
        if short_code in in_memory_links:
            return in_memory_links[short_code]
    return None

def get_user_links(user_id, limit=10):
    try:
        if links_collection is not None:
            links = list(links_collection.find(
                {'user_id': str(user_id), 'is_active': True}
            ).sort('created_at', -1).limit(limit))
            for link in links:
                if '_id' in link:
                    link['_id'] = str(link['_id'])
            return links
        else:
            user_links = [link for link in in_memory_links.values() 
                         if link.get('user_id') == str(user_id)]
            return sorted(user_links, key=lambda x: x['created_at'], reverse=True)[:limit]
    except Exception as e:
        logger.error(f"❌ Failed to get user links: {e}")
        return []

def increment_clicks(short_code):
    try:
        if links_collection is not None:
            result = links_collection.update_one(
                {'short_code': short_code},
                {'$inc': {'clicks': 1}}
            )
            if result.modified_count > 0:
                logger.info(f"✅ Click incremented for {short_code}")
        else:
            if short_code in in_memory_links:
                in_memory_links[short_code]['clicks'] += 1
    except Exception as e:
        logger.error(f"❌ Failed to increment clicks: {e}")
        if short_code in in_memory_links:
            in_memory_links[short_code]['clicks'] += 1

def save_user(user_id, username=None, first_name=None):
    user_data = {
        'user_id': str(user_id),
        'username': username,
        'first_name': first_name,
        'last_seen': datetime.utcnow().isoformat()
    }
    
    try:
        if users_collection is not None:
            result = users_collection.update_one(
                {'user_id': str(user_id)},
                {
                    '$set': user_data,
                    '$setOnInsert': {
                        'first_seen': datetime.utcnow().isoformat(),
                        'links_created': 0
                    }
                },
                upsert=True
            )
            if result.upserted_id:
                logger.info(f"✅ New user saved: {user_id}")
        else:
            if str(user_id) not in in_memory_users:
                user_data['first_seen'] = datetime.utcnow().isoformat()
                user_data['links_created'] = 0
                in_memory_users[str(user_id)] = user_data
                logger.info(f"✅ New user saved in memory: {user_id}")
    except Exception as e:
        logger.error(f"❌ Failed to save user: {e}")

def get_user_stats(user_id):
    try:
        if users_collection is not None:
            user = users_collection.find_one({'user_id': str(user_id)})
            if user:
                if '_id' in user:
                    user['_id'] = str(user['_id'])
                return user
        else:
            if str(user_id) in in_memory_users:
                return in_memory_users[str(user_id)]
    except Exception as e:
        logger.error(f"❌ Failed to get user stats: {e}")
        if str(user_id) in in_memory_users:
            return in_memory_users[str(user_id)]
    return None

# ============= TELEGRAM FUNCTIONS =============

def send_telegram_message(chat_id, text, reply_markup=None, parse_mode='HTML'):
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    
    try:
        response = requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"❌ Failed to send message: {e}")
        return None

def answer_callback_query(callback_query_id, text=None, show_alert=False):
    payload = {'callback_query_id': callback_query_id}
    if text:
        payload['text'] = text
        payload['show_alert'] = show_alert
    
    try:
        response = requests.post(
            f"{TELEGRAM_API_URL}/answerCallbackQuery",
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"❌ Failed to answer callback: {e}")
        return None

# ============= BOT HANDLERS =============

def get_main_keyboard():
    return {
        'inline_keyboard': [
            [
                {'text': '🔗 Shorten URL', 'callback_data': 'shorten'},
                {'text': '📊 My Stats', 'callback_data': 'stats'}
            ],
            [
                {'text': '📝 My Links', 'callback_data': 'my_links'},
                {'text': '❓ Help', 'callback_data': 'help'}
            ]
        ]
    }

def handle_start(chat_id, user_id, username=None, first_name=None):
    save_user(user_id, username, first_name)
    
    welcome_text = f"""
👋 <b>Welcome to {BOT_NAME}!</b>

I can shorten any URL instantly and track all your links.

<b>📋 Commands:</b>
/start - Show this message
/help - Get help and usage guide
/stats - View your statistics
/mylinks - See all your shortened URLs

<b>🔗 How to shorten URLs:</b>
• Simply send me any URL
• Use /custom for custom short codes

<b>✨ Features:</b>
✅ Free & unlimited URL shortening
✅ Custom short codes available
✅ Click tracking
✅ Link management
✅ User statistics

Let's get started! Send me a URL to shorten. 🚀
"""
    send_telegram_message(chat_id, welcome_text, get_main_keyboard())

def handle_help(chat_id):
    help_text = f"""
📖 <b>How to use {BOT_NAME}</b>

<b>1️⃣ Shorten URL (Automatic):</b>
   Just send me any URL and I'll generate a short link for you!
   Example: <code>https://www.example.com/very/long/url</code>

<b>2️⃣ Custom Short Code:</b>
   Use /custom command to create your own short code
   Format: <code>/custom https://example.com yourcode</code>
   Example: <code>/custom https://youtube.com yt</code>

<b>3️⃣ View Your Links:</b>
   Use /mylinks to see all your shortened URLs

<b>4️⃣ Statistics:</b>
   Use /stats to see your usage statistics

<b>5️⃣ Support:</b>
   Contact {BOT_OWNER} for help

<b>📝 Note:</b>
• Short codes are 3-10 characters
• Letters and numbers only
• Must be unique
"""
    send_telegram_message(chat_id, help_text, get_main_keyboard())

def handle_stats(chat_id, user_id):
    user = get_user_stats(user_id)
    if not user:
        send_telegram_message(chat_id, "📊 No statistics found. Create some links first! 🚀", get_main_keyboard())
        return
    
    links_count = len(get_user_links(user_id, limit=1000))
    
    stats_text = f"""
📊 <b>Your Statistics</b>

👤 <b>User ID:</b> <code>{user['user_id']}</code>
📅 <b>First seen:</b> {user.get('first_seen', 'N/A')[:16]}
🔗 <b>Links created:</b> {links_count}

<b>Keep creating more links! 🚀</b>
"""
    send_telegram_message(chat_id, stats_text, get_main_keyboard())

def handle_my_links(chat_id, user_id):
    links = get_user_links(user_id, limit=10)
    
    if not links:
        send_telegram_message(chat_id, "📝 You haven't created any links yet. Send me a URL to start! 🚀", get_main_keyboard())
        return
    
    message = "📝 <b>Your Recent Links</b>\n\n"
    for idx, link in enumerate(links[:5], 1):
        short_url = f"{BASE_URL}/{link['short_code']}"
        created_date = link.get('created_at', '').split('T')[0] if 'created_at' in link else 'N/A'
        message += f"<b>{idx}.</b> 🔗 <a href='{short_url}'>{short_url}</a>\n"
        message += f"   ↳ Clicks: <b>{link.get('clicks', 0)}</b>\n"
        message += f"   ↳ Created: {created_date}\n"
        original = link.get('original_url', '')
        if len(original) > 40:
            original = original[:40] + '...'
        message += f"   ↳ Original: {original}\n\n"
    
    if len(links) > 5:
        message += f"\nAnd {len(links) - 5} more links..."
    
    send_telegram_message(chat_id, message, get_main_keyboard())

def handle_custom_shortcode(chat_id, user_id, args):
    if len(args) < 2:
        message = """
❌ <b>Invalid format!</b>

<b>Usage:</b>
<code>/custom {URL} {short_code}</code>

<b>Examples:</b>
<code>/custom https://youtube.com yt</code>
<code>/custom https://github.com gh</code>

<b>Rules:</b>
• 3-10 characters
• Letters and numbers only
• Must be unique
"""
        send_telegram_message(chat_id, message, get_main_keyboard())
        return
    
    url = args[0]
    short_code = args[1]
    
    if not is_valid_url(url):
        send_telegram_message(chat_id, "❌ Invalid URL. Please check and try again.", get_main_keyboard())
        return
    
    url = normalize_url(url)
    
    if len(short_code) < 3 or len(short_code) > 10:
        send_telegram_message(chat_id, "❌ Short code must be 3-10 characters long.", get_main_keyboard())
        return
    
    if not short_code.isalnum():
        send_telegram_message(chat_id, "❌ Short code can only contain letters and numbers.", get_main_keyboard())
        return
    
    existing = get_link(short_code)
    if existing:
        send_telegram_message(chat_id, f"❌ Short code '<b>{short_code}</b>' is already taken. Please choose another.", get_main_keyboard())
        return
    
    link = save_link(short_code, url, user_id, custom=True)
    if not link:
        send_telegram_message(chat_id, "❌ Failed to create short link. Please try again later.", get_main_keyboard())
        return
    
    short_url = f"{BASE_URL}/{short_code}"
    
    message = f"""
✅ <b>Custom URL Shortened!</b>

🔗 <b>Short URL:</b> <a href='{short_url}'>{short_url}</a>
📎 <b>Original:</b> {url}
📅 <b>Created:</b> Just now

Share your short link! 🚀
"""
    send_telegram_message(chat_id, message, get_main_keyboard())

def handle_url(chat_id, user_id, text):
    if not is_valid_url(text):
        send_telegram_message(chat_id, "❌ Invalid URL. Please send a valid URL like: https://example.com", get_main_keyboard())
        return
    
    url = normalize_url(text)
    
    short_code = None
    for attempt in range(5):
        code = generate_short_code()
        existing = get_link(code)
        if not existing:
            short_code = code
            break
    
    if not short_code:
        send_telegram_message(chat_id, "❌ Unable to generate a unique short code. Please try again.", get_main_keyboard())
        return
    
    link = save_link(short_code, url, user_id)
    if not link:
        send_telegram_message(chat_id, "❌ Failed to create short link. Please try again later.", get_main_keyboard())
        return
    
    save_user(user_id)
    
    short_url = f"{BASE_URL}/{short_code}"
    
    message = f"""
✅ <b>URL Shortened Successfully!</b>

🔗 <b>Short URL:</b> <a href='{short_url}'>{short_url}</a>
📎 <b>Original:</b> {url}
📅 <b>Created:</b> Just now
🔄 <b>Views:</b> 0

<b>Want a custom short code?</b>
Try: <code>/custom {url} mycode</code>

Share your short link! 🚀
"""
    send_telegram_message(chat_id, message, get_main_keyboard())

def handle_callback_query(callback_query):
    callback_id = callback_query['id']
    chat_id = callback_query['message']['chat']['id']
    user_id = callback_query['from']['id']
    data = callback_query['data']
    
    answer_callback_query(callback_id)
    
    if data == 'shorten':
        send_telegram_message(chat_id, "📥 Send me any URL and I'll shorten it for you!", get_main_keyboard())
    elif data == 'stats':
        handle_stats(chat_id, user_id)
    elif data == 'my_links':
        handle_my_links(chat_id, user_id)
    elif data == 'help':
        handle_help(chat_id)

# ============= FLASK ROUTES =============

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'status': '🟢 Online',
        'bot': BOT_NAME,
        'username': BOT_USERNAME,
        'version': '2.0.0',
        'timestamp': datetime.utcnow().isoformat(),
        'webhook_url': WEBHOOK_URL,
        'mongo_status': 'Connected' if mongo_client else '⚠️ Using memory storage',
        'port': PORT,
        'base_url': BASE_URL
    })

@app.route('/health', methods=['GET'])
def health():
    mongo_status = '✅ Connected' if mongo_client else '⚠️ Memory only'
    links_count = len(in_memory_links) if not mongo_client else 0
    
    return jsonify({
        'status': 'healthy',
        'mongo': mongo_status,
        'memory_links': links_count,
        'port': PORT,
        'timestamp': datetime.utcnow().isoformat()
    })

@app.route('/<short_code>', methods=['GET'])
def redirect_to_url(short_code):
    link = get_link(short_code)
    
    if not link:
        return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Link Not Found</title>
                <style>
                    body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
                    h1 { color: #ff6b6b; }
                    .container { max-width: 600px; margin: 0 auto; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>🔗 404 - Link Not Found</h1>
                    <p>The short link you're looking for doesn't exist or has been removed.</p>
                    <p><a href="/">Go to Home</a></p>
                </div>
            </body>
            </html>
        '''), 404
    
    increment_clicks(short_code)
    return redirect(link['original_url'], 302)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"📨 Webhook received")
        
        if 'message' in data:
            message = data['message']
            chat_id = message['chat']['id']
            user_id = message['from']['id']
            username = message['from'].get('username')
            first_name = message['from'].get('first_name')
            
            if 'text' in message:
                text = message['text'].strip()
                
                if text.startswith('/start'):
                    handle_start(chat_id, user_id, username, first_name)
                elif text.startswith('/help'):
                    handle_help(chat_id)
                elif text.startswith('/stats'):
                    handle_stats(chat_id, user_id)
                elif text.startswith('/mylinks'):
                    handle_my_links(chat_id, user_id)
                elif text.startswith('/custom'):
                    args = text.split()[1:]
                    handle_custom_shortcode(chat_id, user_id, args)
                else:
                    if is_valid_url(text):
                        handle_url(chat_id, user_id, text)
                    else:
                        send_telegram_message(
                            chat_id,
                            "❌ Invalid command or URL.\n\nSend me a URL to shorten or use /help for commands.",
                            get_main_keyboard()
                        )
        
        elif 'callback_query' in data:
            callback_query = data['callback_query']
            handle_callback_query(callback_query)
        
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/set_webhook', methods=['GET'])
def set_webhook_endpoint():
    try:
        response = requests.get(
            f"{TELEGRAM_API_URL}/setWebhook",
            params={'url': WEBHOOK_URL},
            timeout=10
        )
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/delete_webhook', methods=['GET'])
def delete_webhook_endpoint():
    try:
        response = requests.get(
            f"{TELEGRAM_API_URL}/deleteWebhook",
            timeout=10
        )
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/webhook_info', methods=['GET'])
def webhook_info():
    try:
        response = requests.get(
            f"{TELEGRAM_API_URL}/getWebhookInfo",
            timeout=10
        )
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============= SETUP WEBHOOK =============

def setup_webhook():
    try:
        # Delete existing webhook
        delete_response = requests.get(f"{TELEGRAM_API_URL}/deleteWebhook", timeout=5)
        logger.info(f"📋 Delete webhook response: {delete_response.json()}")
        
        # Set new webhook
        response = requests.get(
            f"{TELEGRAM_API_URL}/setWebhook",
            params={'url': WEBHOOK_URL},
            timeout=10
        )
        result = response.json()
        
        if result.get('ok'):
            logger.info(f"✅ Webhook set successfully: {WEBHOOK_URL}")
        else:
            logger.error(f"❌ Failed to set webhook: {result}")
            
    except Exception as e:
        logger.error(f"❌ Webhook setup error: {e}")

# ============= MAIN ENTRY POINT =============

if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info(f"🚀 Starting {BOT_NAME}")
    logger.info(f"📱 Username: @{BOT_USERNAME}")
    logger.info(f"🌐 Base URL: {BASE_URL}")
    logger.info(f"🔗 Webhook URL: {WEBHOOK_URL}")
    logger.info(f"🔌 Port: {PORT}")
    logger.info(f"🗄️  MongoDB: {'Connected' if mongo_client else 'Memory Only'}")
    logger.info("=" * 50)
    
    # Setup webhook
    setup_webhook()
    
    # Get webhook info
    try:
        response = requests.get(f"{TELEGRAM_API_URL}/getWebhookInfo", timeout=5)
        info = response.json()
        logger.info(f"📋 Webhook info: {info}")
    except Exception as e:
        logger.error(f"❌ Failed to get webhook info: {e}")
    
    # Start Flask app
    logger.info(f"✅ Bot is ready! Listening on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
