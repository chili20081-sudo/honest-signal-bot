import os
import re
import time
import random
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

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

def search_kad(case_number):
    session = requests.Session()
    ua = random.choice(USER_AGENTS)
    base_headers = {
        "User-Agent": ua,
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    # Visit main page first to get session cookies
    try:
        session.get(
            "https://kad.arbitr.ru/",
            headers={**base_headers, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            timeout=15
        )
        time.sleep(random.uniform(0.8, 1.8))
    except Exception:
        pass
    url = "https://kad.arbitr.ru/Kad/SearchInstances"
    headers = {
        **base_headers,
        "Content-Type": "application/json",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://kad.arbitr.ru/",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://kad.arbitr.ru",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    payload = {
        "Page": 1, "Count": 25, "Courts": [], "Judges": [],
        "Plaintiffs": [], "Defendants": [],
        "Cases": [{"ExactMatch": True, "Value": case_number}],
        "DateFrom": None, "DateTo": None, "SessionDateFrom": None,
        "SessionDateTo": None, "FinalDocument": None,
        "WithVKSInstances": False, "Sides": []
    }
    last_error = None
    for attempt in range(3):
        try:
            if attempt > 0:
                time.sleep(3 + attempt * 2)
                ua = random.choice(USER_AGENTS)
                headers["User-Agent"] = ua
            resp = session.post(url, json=payload, headers=headers, timeout=30)
            if resp.status_code in (429, 503):
                last_error = f"Сервис kad.arbitr.ru временно ограничил доступ (код {resp.status_code}). Попробуйте через минуту."
                continue
            if resp.status_code == 200:
                return resp.json()
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            last_error = "Таймаут при обращении к kad.arbitr.ru. Попробуйте позже."
        except Exception as e:
            last_error = str(e)
    raise Exception(last_error or "Не удалось получить ответ от kad.arbitr.ru")

def format_case_info(data, case_number):
    result = data.get('Result')
    if not result:
        return f"По делу {case_number} ничего не найдено."
    items = result.get('Items', [])
    if not items:
        return f"По делу {case_number} ничего не найдено."
    lines = [f"📋 Найдено дел: {len(items)}\n"]
    for item in items[:5]:
        case_id = item.get('CaseId', '')
        court = item.get('CourtName', 'Неизвестно')
        judge = item.get('Judge', 'Не указан')
        date = item.get('DateDocument', '')[:10] if item.get('DateDocument') else 'Нет данных'
        sides = item.get('Sides', [])
        plaintiffs = [s['Name'] for s in sides if s.get('SideTypeId') == 1]
        defendants = [s['Name'] for s in sides if s.get('SideTypeId') == 2]
        lines.append(f"⚖️ Дело: {case_id}")
        lines.append(f"🏛 Суд: {court}")
        lines.append(f"👨‍⚖️ Судья: {judge}")
        lines.append(f"📅 Дата: {date}")
        if plaintiffs:
            lines.append(f"📌 Истец: {', '.join(plaintiffs[:2])}")
        if defendants:
            lines.append(f"📌 Ответчик: {', '.join(defendants[:2])}")
        lines.append("")
    return "\n".join(lines)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот для поиска арбитражных дел.\n"
        "Отправьте номер дела (например, А40-12345/2023) или задайте любой вопрос."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    match = CASE_PATTERN.search(text)
    if match:
        case_number = match.group(0)
        await update.message.reply_text(f"🔍 Ищу дело {case_number}...")
        try:
            data = search_kad(case_number)
            reply = format_case_info(data, case_number)
        except Exception as e:
            err = str(e)
            if "ограничил" in err or "429" in err or "503" in err:
                reply = f"⚠️ {err}\nПопробуйте повторить запрос через 1-2 минуты."
            elif "Таймаут" in err:
                reply = f"⏱️ {err}"
            else:
                reply = f"❌ Ошибка при поиске дела: {err}"
        await update.message.reply_text(reply)
    else:
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{"role": "user", "content": text}]
            )
            reply = message.content[0].text
        except anthropic.RateLimitError:
            reply = "⏳ Достигнут лимит запросов к Claude. Лимит сбрасывается каждый день в 02:00 по Москве. Попробуйте позже."
        except anthropic.APIError as e:
            reply = f"❌ Ошибка API Claude: {str(e)}"
        except Exception as e:
            reply = f"❌ Ошибка: {str(e)}"
        await update.message.reply_text(reply)

def run_bot():
    asyncio.set_event_loop(asyncio.new_event_loop())
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling(drop_pending_updates=True, stop_signals=())

def main():
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    main()
