import telebot
import time
import threading

BOT_TOKEN = "8614082158:AAHIPZpqVvy4EzSKBJmFYBaVst-xtj4m-l0"
ADMIN_ID = 7578145913

KEYWORDS = ["You received"]

FORWARD_RULES = {
    -1004330276394: [-5580596463],
    -5353420212: [-5350880041],
    -5339749243: [-5100231154, -5306739731],
}

bot = telebot.TeleBot(BOT_TOKEN)

def notify_admin(msg):
    try:
        bot.send_message(ADMIN_ID, msg)
    except Exception as e:
        print('Could not notify admin: ' + str(e))

@bot.message_handler(content_types=['text'])
def forward_text(message):
    if message.chat.id in FORWARD_RULES:
        text = message.text.lower()
        if any(kw.lower() in text for kw in KEYWORDS):
            for target in FORWARD_RULES[message.chat.id]:
                try:
                    bot.send_message(target, message.text)
                    print('Message forwarded!')
                except Exception as e:
                    print('Error: ' + str(e))
        else:
            print('Skipped - no keyword match')

print('Bot is running...')
notify_admin('✅ Bot is now ONLINE and running!')

while True:
    try:
        bot.polling(none_stop=True, allowed_updates=['message'])
    except Exception as e:
        print('Bot crashed: ' + str(e))
        notify_admin('❌ Bot went DOWN! Restarting...
Error: ' + str(e))
        time.sleep(5)
        notify_admin('✅ Bot is back ONLINE!')
