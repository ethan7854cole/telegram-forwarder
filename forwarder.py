import telebot

BOT_TOKEN = "8614082158:AAHIPZpqVvy4EzSKBJmFYBaVst-xtj4m-l0"
SOURCE_GROUP_ID = -1004330276394
TARGET_GROUP_ID = -5580596463

KEYWORDS = ["Total in"]

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(content_types=['text'])
def forward_text(message):
    if message.chat.id == SOURCE_GROUP_ID:
        text = message.text.lower()
        if any(kw.lower() in text for kw in KEYWORDS):
            try:
                bot.send_message(TARGET_GROUP_ID, message.text)
                print('Message forwarded!')
            except Exception as e:
                print('Error: ' + str(e))
        else:
            print('Skipped - no keyword match')

print('Bot is running with keyword filter...')
bot.polling(none_stop=True, allowed_updates=['message'])
