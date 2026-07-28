import telebot

BOT_TOKEN = "8614082158:AAHIPZpqVvy4EzSKBJmFYBaVst-xtj4m-l0"
SOURCE_GROUP_ID = -1004330276394
TARGET_GROUP_ID = -5580596463

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(content_types=['text'])
def forward_text(message):
    if message.chat.id == SOURCE_GROUP_ID:
        try:
            bot.send_message(TARGET_GROUP_ID, message.text)
            print('Message sent!')
        except Exception as e:
            print('Error: ' + str(e))

@bot.message_handler(content_types=['photo'])
def forward_photo(message):
    if message.chat.id == SOURCE_GROUP_ID:
        try:
            bot.send_photo(TARGET_GROUP_ID, message.photo[-1].file_id, caption=message.caption)
        except Exception as e:
            print('Error: ' + str(e))

@bot.message_handler(content_types=['video'])
def forward_video(message):
    if message.chat.id == SOURCE_GROUP_ID:
        try:
            bot.send_video(TARGET_GROUP_ID, message.video.file_id, caption=message.caption)
        except Exception as e:
            print('Error: ' + str(e))

@bot.message_handler(content_types=['document'])
def forward_document(message):
    if message.chat.id == SOURCE_GROUP_ID:
        try:
            bot.send_document(TARGET_GROUP_ID, message.document.file_id, caption=message.caption)
        except Exception as e:
            print('Error: ' + str(e))

print('Bot is running...')
bot.polling(none_stop=True, allowed_updates=['message'])
