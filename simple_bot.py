import os
from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
OPENAI_API_KEY = "sk-..."
TELEGRAM_TOKEN = "123456:ABC..."
client = OpenAI(api_key=OPENAI_API_KEY)
assistant = client.beta.assistants.create(
    name="Мой первый агент",
    instructions="""Ты дружелюбный помощник. 
    Отвечай кратко и понятно. 
    Если не знаешь ответа - честно скажи об этом.
    Используй эмодзи в ответах!""",
    model="gpt-4o",
)
print(f"✅ Агент создан! ID: {assistant.id}")
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветственное сообщение"""
    await update.message.reply_text(
        "👋 Привет! Я твой первый AI-агент!\n"
        "Задай мне любой вопрос, и я отвечу."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений от пользователя"""
    await update.message.chat.send_action(action="typing")
    user_text = update.message.text
    try:
        thread = client.beta.threads.create()
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_text)
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant.id
        )
        import time
        while run.status != "completed":
            time.sleep(0.5)
            run = client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )
            messages = client.beta.threads.messages.list(
            thread_id=thread.id
        )
        agent_response = messages.data[0].content[0].text.value
        await update.message.reply_text(agent_response)
    except Exception as e:
            await update.message.reply_text(f"😕 Ошибка: {str(e)}")
def main():
    """Запускаем Telegram бота"""
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 Бот запущен! Нажми Ctrl+C для остановки")
    app.run_polling()
if __name__ == "__main__":
    main()
    
            
        
    