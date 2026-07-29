import os
import telebot
import time
from datetime import datetime

# Read token directly from Railway variables
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

ADMIN_ID = 7578145913
KEYWORDS = ['You received']

FORWARD_RULES = {
    -1003894781195: [-1005580596463],
    -5353420212: [-5350880041],
    -5339749243: [-5100231154, -5306739731],
}

forwarded_count = 0
today_count = 0
start_time = datetime.now()
last_messages = []

bot = telebot.TeleBot(BOT_TOKEN)

def notify_admin(msg):
    try:
        bot.send_message(ADMIN_ID, msg)
    except Exception as e:
        print(f"Notify Admin Error: {e}", flush=True)

def get_uptime():
    uptime = datetime.now() - start_time
    hours = int(uptime.total_seconds() // 3600)
    minutes = int((uptime.total_seconds() % 3600) // 60)
    return f"{hours}h {minutes}m"

@bot.message_handler(commands=['start'])
def start(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, 'Bot is running. Use /help to see all commands.')

@bot.message_handler(commands=['status'])
def status(message):
    if message.chat.id == ADMIN_ID:
        txt = f"Bot Online\nGroups: {len(FORWARD_RULES)}\nForwarded: {forwarded_count}\nUptime: {get_uptime()}"
        bot.reply_to(message, txt)

@bot.message_handler(commands=['ping'])
def ping(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, 'Pong! Bot is alive.')

@bot.message_handler(content_types=['text'])
def forward_text(message):
    global forwarded_count, today_count
    print(f"📩 [MSG RECEIVED] Chat ID: {message.chat.id} | Text: '{message.text}'", flush=True)
    
    if message.chat.id in FORWARD_RULES:
        text = message.text.lower()
        if any(kw.lower() in text for kw in KEYWORDS):
            print("✅ [KEYWORD MATCH] Forwarding message...", flush=True)
            for target in FORWARD_RULES[message.chat.id]:
                try:
                    bot.send_message(target, message.text)
                    print(f"🚀 [FORWARD SUCCESS] Sent to {target}", flush=True)
                    forwarded_count += 1
                    today_count += 1
                    last_messages.append(message.text[:50])
                    if len(last_messages) > 10:
                        last_messages.pop(0)
                except Exception as e:
                    print(f"❌ [FORWARD ERROR] Target {target}: {e}", flush=True)
        else:
            print("⚠️ [SKIP] Message does not contain keyword 'You received'.", flush=True)
    else:
        print(f"⚠️ [SKIP] Chat ID {message.chat.id} is not in FORWARD_RULES.", flush=True)

print('Bot running...', flush=True)
notify_admin('Bot is ONLINE. Use /help to see all commands.')

while True:
    try:
        bot.polling(none_stop=True, allowed_updates=['message'])
    except Exception as e:
        print(f"Polling Error: {e}", flush=True)
        time.sleep(5)
