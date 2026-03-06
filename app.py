import os
import re
import asyncio
import logging
import threading
import requests
import anthropic
from flask import Flask
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return 'OK', 200

CASE_PATTERN = re.compile(r'[АAаa]\d+-\d+/\d{4}', re.IGNORECASE)

def search_kad(case_number):
    url = "https://kad.arbitr.ru/Kad/SearchInstances"
    headers = {
        "Content-Type": "application/json",
        "Referer": "https://kad.arbitr.ru/",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    payload = {
        "Page": 1,
        "Count": 25,
        "Courts": [],
        "Judges": [],
        "Plaintiffs": [],
        "Defendants": [],
        "Cases": [{"ExactMatch": True, "Value": case_number}],
        "DateFrom": None,
        "DateTo": None,
        "SessionDateFrom": None,
        "SessionDateTo": None,
        "FinalDocument": None,
        "WithVKSInstances": False,
        "Sides": []
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()

def format_case_info(data, case_number):
    items = data.get('Result', {}).get('Items', [])
    if not items:
        return f"❌ Дело *{case_number}* не найдено в картотеке арбитражных дел."
    
    case = items[0]
    court = case.get('CourtName', 'Н/Д')
    judge = case.get('Judge', 'Н/Д')
    date_str = case.get('Date', '')
    if date_str:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            date_str = dt.strftime('%d.%m.%Y')
        except:
            date_str = date_str[:10]
    
    plaintiffs = [s.get('Name', '') for s in case.get('Sides', []) if s.get('SideType') == 'Plaintiff']
    defendants = [s.get('Name', '') for s in case.get('Sides', []) if s.get('SideType') == 'Defendant']
    
    instances = case.get('Instances', [])
    last_doc = ''
    if instances:
        last = instances[-1]
        last_doc = last.get('DocumentName', '') or last.get('CaseResult', '')
    
    card_id = case.get('CaseId', '')
    link = f"https://kad.arbitr.ru/Card/{card_id}" if card_id else "https://kad.arbitr.ru"
    
    lines = [
        f"⚖️ *Дело {case_number}*",
        f"🏛 Суд: {court}",
        f"👨‍⚖️ Судья: {judge}",
        f"📅 Дата: {date_str}",
    ]
    if plaintiffs:
        lines.append(f"📋 Истец: {'; '.join(plaintiffs[:2])}")
    if defendants:
        lines.append(f"📋 Ответчик: {'; '.join(defendants[:2])}")
    if last_doc:
        lines.append(f"📄 Последнее решение: {last_doc}")
    lines.append(f"🔗 [Открыть дело]({link})")
    
    return '\n'.join(lines)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я помогу найти информацию по арбитражным делам.\n\n"
        "Отправьте номер дела (например: А18-333/2025) — и я найду его в картотеке.\n\n"
        "Или задайте любой вопрос — отвечу с помощью Claude AI."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    match = CASE_PATTERN.search(text)
    
    if match:
        case_number = match.group(0)
        # Normalize Cyrillic А
        case_number = re.sub(r'^[Aa]', 'А', case_number)
        
        await update.message.reply_text("🔍 Ищу дело...")
        try:
            data = search_kad(case_number)
            result = format_case_info(data, case_number)
            await update.message.reply_text(result, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error searching kad: {e}")
            await update.message.reply_text(f"❌ Ошибка при поиске дела: {str(e)}")
    else:
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=1024,
                system="Ты полезный ассистент. Отвечай кратко и по делу на русском языке.",
                messages=[{"role": "user", "content": text}]
            )
            await update.message.reply_text(msg.content[0].text)
        except Exception as e:
            logger.error(f"Error calling Claude: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

def run_bot():
    async def async_main():
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        await app.run_polling(drop_pending_updates=True)
    
    asyncio.run(async_main())

def main():
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    main()
