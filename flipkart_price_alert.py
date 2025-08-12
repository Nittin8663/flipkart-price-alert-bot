import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Data file paths
DATA_FILE = 'product_alerts.json'
CONFIG_FILE = 'config.json'

# Load config
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"telegram_token": "YOUR_TELEGRAM_BOT_TOKEN", "check_interval_minutes": 60}
    
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

config = load_config()

# Load and save product data
def load_products():
    if not os.path.exists(DATA_FILE):
        return {}
    
    with open(DATA_FILE, 'r') as f:
        return json.load(f)

def save_products(products):
    with open(DATA_FILE, 'w') as f:
        json.dump(products, f, indent=4)

# Flipkart scraping functions
def extract_product_id(url):
    # Extract product ID from Flipkart URL
    match = re.search(r'pid=([^&]+)', url)
    if match:
        return match.group(1)
    return None

def get_product_details(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract product name
        product_name = soup.select_one('span.B_NuCI')
        if not product_name:
            product_name = soup.select_one('h1 span')
        
        # Extract price
        price_element = soup.select_one('div._30jeq3._16Jk6d')
        
        if not price_element or not product_name:
            return None
        
        # Clean up price - remove non-numeric characters
        price_text = price_element.text.strip()
        price = int(''.join(filter(str.isdigit, price_text)))
        
        # Get product image
        img_element = soup.select_one('img._396cs4')
        img_url = img_element['src'] if img_element else None
        
        return {
            'name': product_name.text.strip(),
            'price': price,
            'url': url,
            'image': img_url
        }
        
    except Exception as e:
        logger.error(f"Error fetching product details: {e}")
        return None

# Telegram bot commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Welcome to Flipkart Price Alert Bot!\n\n'
        'Commands:\n'
        '/add <Flipkart URL> <target price> - Add a new price alert\n'
        '/list - List all your price alerts\n'
        '/remove <alert id> - Remove a price alert\n'
        '/check - Manually check all your price alerts'
    )

async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    # Check if arguments are provided
    if len(context.args) < 2:
        await update.message.reply_text('Please provide a Flipkart URL and target price. Example: /add https://www.flipkart.com/product-page 1000')
        return
    
    # Parse arguments
    url = context.args[0]
    try:
        target_price = int(context.args[1])
    except ValueError:
        await update.message.reply_text('Invalid price. Please provide a numeric value.')
        return
    
    if 'flipkart.com' not in url:
        await update.message.reply_text('Please provide a valid Flipkart URL.')
        return
    
    # Fetch product details
    await update.message.reply_text('Fetching product details, please wait...')
    product_details = get_product_details(url)
    
    if not product_details:
        await update.message.reply_text('Failed to fetch product details. Please check the URL and try again.')
        return
    
    # Load existing data
    products = load_products()
    
    # Initialize user's data if not exists
    if user_id not in products:
        products[user_id] = []
    
    # Add product alert
    product_id = extract_product_id(url) or str(len(products[user_id]))
    alert = {
        'id': product_id,
        'name': product_details['name'],
        'url': url,
        'current_price': product_details['price'],
        'target_price': target_price,
        'added_on': time.time()
    }
    
    products[user_id].append(alert)
    save_products(products)
    
    await update.message.reply_text(
        f'✅ Price alert added!\n\n'
        f'Product: {product_details["name"]}\n'
        f'Current Price: ₹{product_details["price"]}\n'
        f'Target Price: ₹{target_price}\n\n'
        f'You will be notified when the price drops below your target.'
    )

async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    products = load_products()
    
    if user_id not in products or not products[user_id]:
        await update.message.reply_text('You have no active price alerts.')
        return
    
    message = 'Your active price alerts:\n\n'
    
    for i, alert in enumerate(products[user_id]):
        message += f'{i+1}. {alert["name"]}\n'
        message += f'   Current Price: ₹{alert["current_price"]}\n'
        message += f'   Target Price: ₹{alert["target_price"]}\n'
        message += f'   ID: {alert["id"]}\n\n'
    
    await update.message.reply_text(message)

async def remove_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    if not context.args:
        await update.message.reply_text('Please provide the alert ID to remove. Use /list to see all your alerts with IDs.')
        return
    
    alert_id = context.args[0]
    
    products = load_products()
    
    if user_id not in products or not products[user_id]:
        await update.message.reply_text('You have no active price alerts.')
        return
    
    # Find and remove the alert
    found = False
    for i, alert in enumerate(products[user_id]):
        if str(alert['id']) == alert_id:
            removed_alert = products[user_id].pop(i)
            found = True
            break
    
    if found:
        save_products(products)
        await update.message.reply_text(f'✅ Price alert removed: {removed_alert["name"]}')
    else:
        await update.message.reply_text(f'❌ No price alert found with ID: {alert_id}')

async def check_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    await update.message.reply_text('Checking prices for your alerts, please wait...')
    await check_all_prices(context, [user_id])

# Function to check all prices and send notifications
async def check_all_prices(context, specific_users=None):
    products = load_products()
    updates_found = False
    
    users_to_check = specific_users if specific_users else products.keys()
    
    for user_id in users_to_check:
        if user_id not in products:
            continue
        
        user_updates = []
        
        for i, alert in enumerate(products[user_id]):
            try:
                product_details = get_product_details(alert['url'])
                
                if not product_details:
                    continue
                
                current_price = product_details['price']
                old_price = alert['current_price']
                
                # Update the current price
                products[user_id][i]['current_price'] = current_price
                
                # Check if target price is reached
                if current_price <= alert['target_price'] and old_price > alert['target_price']:
                    user_updates.append({
                        'name': alert['name'],
                        'old_price': old_price,
                        'current_price': current_price,
                        'target_price': alert['target_price'],
                        'url': alert['url']
                    })
            except Exception as e:
                logger.error(f"Error checking price for {alert['url']}: {e}")
    
        # Send notification if there are updates
        if user_updates:
            updates_found = True
            message = '🔔 Price Alert! The following products have reached your target price:\n\n'
            
            for update_info in user_updates:
                message += f'🛒 {update_info["name"]}\n'
                message += f'   Old Price: ₹{update_info["old_price"]}\n'
                message += f'   Current Price: ₹{update_info["current_price"]} ✅\n'
                message += f'   Target Price: ₹{update_info["target_price"]}\n'
                message += f'   Link: {update_info["url"]}\n\n'
            
            try:
                await context.bot.send_message(chat_id=user_id, text=message)
            except Exception as e:
                logger.error(f"Failed to send notification to {user_id}: {e}")
    
    # Save updated prices
    if updates_found:
        save_products(products)
    
    return updates_found

async def scheduled_price_check(context):
    await check_all_prices(context)

# Main function
async def main():
    # Initialize the bot
    config = load_config()
    
    if config["telegram_token"] == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("Please set your Telegram bot token in config.json")
        return
    
    application = ApplicationBuilder().token(config["telegram_token"]).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CommandHandler("add", add_product))
    application.add_handler(CommandHandler("list", list_products))
    application.add_handler(CommandHandler("remove", remove_product))
    application.add_handler(CommandHandler("check", check_prices))
    
    # Schedule periodic price checks
    check_interval = config.get("check_interval_minutes", 60)
    job_queue = application.job_queue
    job_queue.run_repeating(scheduled_price_check, interval=check_interval*60)
    
    # Start the bot
    await application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
