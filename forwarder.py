import telebot
import time
from datetime import datetime

BOT_TOKEN = "8614082158:AAHIPZpqVvy4EzSKBJmFYBaVst-xtj4m-l0"
ADMIN_ID = 7578145913
KEYWORDS = ["You received"]
FORWARD_RULES = {
    -1004330276394: [-5580596463],
    -5353420212: [-5350880041],
    -5339749243: [-5100231154, -5306739731],
}
forwarded_count = 0
start_time = datetime.now()
bot = telebot.TeleBot(BOT_TOKEN)

def notify_admin(msg):
    try:
        bot.send_message(ADMIN_ID, msg)
    except Exception as e:
        print(str(e))

@bot.message_handler(commands=["start"])
def start(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "Bot is running. Use /status to check.")

@bot.message_handler(commands=["status"])
def status(message):
    if message.chat.id == ADMIN_ID:
        uptime = datetime.now() - start_time
        hours = int(uptime.total_seconds() // 3600)
        minutes = int((uptime.total_seconds() % 3600) // 60)
        bot.reply_to(message, "Bot Online. Groups: " + str(len(FORWARD_RULES)) + ". Forwarded: " + str(forwarded_count) + ". Uptime: " + str(hours) + "h " + str(minutes) + "m")

@bot.message_handler(commands=["help"])
def help(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "/status /start /stop /help")

@bot.message_handler(content_types=["text"])
def forward_text(message):
    global forwarded_count
    if message.chat.id in FORWARD_RULES:
        text = message.text.lower()
        if any(kw.lower() in text for kw in KEYWORDS):
            for target in FORWARD_RULES[message.chat.id]:
                try:
                    bot.send_message(target, message.text)
                    forwarded_count += 1
                except Exception as e:
                    print(str(e))

print("Bot running...")
notify_admin("Bot is ONLINE. Use /status to check.")
while True:
    try:
        bot.polling(none_stop=True, allowed_updates=["message"])
    except Exception as e:
        notify_admin("Bot DOWN. Restarting. Error: " + str(e))
        time.sleep(5)
        notify_admin("Bot is back ONLINE.")
