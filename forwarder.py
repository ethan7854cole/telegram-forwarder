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
today_count = 0
start_time = datetime.now()
last_messages = []
bot = telebot.TeleBot(BOT_TOKEN)

def notify_admin(msg):
    try:
        bot.send_message(ADMIN_ID, msg)
    except Exception as e:
        print(str(e))

def get_uptime():
    uptime = datetime.now() - start_time
    hours = int(uptime.total_seconds() // 3600)
    minutes = int((uptime.total_seconds() % 3600) // 60)
    return str(hours) + "h " + str(minutes) + "m"

@bot.message_handler(commands=["start"])
def start(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "Bot is running. Use /help to see all commands.")

@bot.message_handler(commands=["status"])
def status(message):
    if message.chat.id == ADMIN_ID:
        lines = ["Bot Online", "Groups: " + str(len(FORWARD_RULES)), "Forwarded: " + str(forwarded_count), "Uptime: " + get_uptime()]
        bot.reply_to(message, chr(10).join(lines))

@bot.message_handler(commands=["ping"])
def ping(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "Pong! Bot is alive.")

@bot.message_handler(commands=["groups"])
def groups(message):
    if message.chat.id == ADMIN_ID:
        lines = ["Active Groups:"]
        for src, name in GROUP_NAMES.items():
            lines.append(name)
        bot.reply_to(message, chr(10).join(lines))

@bot.message_handler(commands=["keyword"])
def keyword(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "Active keywords: " + ", ".join(KEYWORDS))

@bot.message_handler(commands=["addkeyword"])
def addkeyword(message):
    if message.chat.id == ADMIN_ID:
        parts = message.text.split(None, 1)
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /addkeyword word")
            return
        kw = parts[1].strip()
        if kw not in KEYWORDS:
            KEYWORDS.append(kw)
            bot.reply_to(message, "Added: " + kw + ". All: " + ", ".join(KEYWORDS))
        else:
            bot.reply_to(message, "Keyword already exists.")

@bot.message_handler(commands=["removekeyword"])
def removekeyword(message):
    if message.chat.id == ADMIN_ID:
        parts = message.text.split(None, 1)
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /removekeyword word")
            return
        kw = parts[1].strip()
        if kw in KEYWORDS:
            KEYWORDS.remove(kw)
            bot.reply_to(message, "Removed: " + kw + ". All: " + ", ".join(KEYWORDS))
        else:
            bot.reply_to(message, "Keyword not found.")

@bot.message_handler(commands=["count"])
def count(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "Total: " + str(forwarded_count) + ". Today: " + str(today_count))

@bot.message_handler(commands=["history"])
def history(message):
    if message.chat.id == ADMIN_ID:
        if not last_messages:
            bot.reply_to(message, "No messages forwarded yet.")
        else:
            lines = ["Last forwarded messages:"]
            for i, msg in enumerate(last_messages[-5:], 1):
                lines.append(str(i) + ". " + msg)
            bot.reply_to(message, chr(10).join(lines))

@bot.message_handler(commands=["report"])
def report(message):
    if message.chat.id == ADMIN_ID:
        lines = ["Daily Report:", "Total: " + str(forwarded_count), "Today: " + str(today_count), "Keywords: " + ", ".join(KEYWORDS), "Groups: " + str(len(FORWARD_RULES)), "Uptime: " + get_uptime()]
        bot.reply_to(message, chr(10).join(lines))

@bot.message_handler(commands=["test"])
def test(message):
    if message.chat.id == ADMIN_ID:
        success = 0
        fail = 0
        for src, targets in FORWARD_RULES.items():
            for target in targets:
                try:
                    bot.send_message(target, "Test message from bot. All systems working.")
                    success += 1
                except Exception as e:
                    fail += 1
        bot.reply_to(message, "Test done. Success: " + str(success) + ". Failed: " + str(fail))

@bot.message_handler(commands=["help"])
def help(message):
    if message.chat.id == ADMIN_ID:
        lines = ["Commands:", "/status", "/ping", "/groups", "/keyword", "/addkeyword word", "/removekeyword word", "/count", "/history", "/report", "/test", "/help"]
        bot.reply_to(message, chr(10).join(lines))

@bot.message_handler(content_types=["text"])
def forward_text(message):
    global forwarded_count, today_count
    if message.chat.id in FORWARD_RULES:
        text = message.text.lower()
        if any(kw.lower() in text for kw in KEYWORDS):
            for target in FORWARD_RULES[message.chat.id]:
                try:
                    bot.send_message(target, message.text)
                    forwarded_count += 1
                    today_count += 1
                    last_messages.append(message.text[:50])
                    if len(last_messages) > 10:
                        last_messages.pop(0)
                except Exception as e:
                    print(str(e))

print("Bot running...")
notify_admin("Bot is ONLINE. Use /help to see all commands.")
while True:
    try:
        bot.polling(none_stop=True, allowed_updates=["message"])
    except Exception as e:
        notify_admin("Bot DOWN. Restarting. Error: " + str(e))
        time.sleep(5)
        notify_admin("Bot is back ONLINE.")
