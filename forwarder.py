import telebot

BOT_TOKEN = "8614082158:AAHIPZpqVvy4EzSKBJmFYBaVst-xtj4m-l0"

KEYWORDS = ["You received"]

FORWARD_RULES = {
    -1004330276394: [-5580596463],
}

bot = telebot.TeleBot(BOT_TOKEN)

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
bot.polling(none_stop=True, allowed_updates=['message'])
