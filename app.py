import os
import re
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
    headers = {"Content-Type": "application/json", "Referer": "https://kad.arbitr.ru/", "X-Requested-With": "XMLHttpRequest"}
    payload = {"Page": 1, "Count": 25, "Courts": [], "Judges": [], "Plaintiffs": [], "Defendants": [],
        "Cases": [{"ExactMatch": True, "Value": case_number}],
        "DateFrom": None, "DateTo": None, "SessionDateFrom": None, "SessionDateTo": None,
        "FinalDocument": None, "WithVKSInstances": False, "Sides": []}
    resp = requests.post(url, json=payload, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()


def format_case_info(data, case_number):
    try:
        items = data.get('Result', {}).get('Items', [])
        if not items:
            return f"❌ Дело *{case_number}* не найдено."
        case = items[0]
        plaintiffs = [p.get('Name','').strip() for p in case.get('Plaintiffs',[]) if p.get('Name')]
        defendants = [d.get('Name','').strip() for d in case.get('Defendants',[]) if d.get('Name')]
        court = case.get('CourtName','')
        judge = case.get('Judge','')
        reg_date = case.get('RegistrationDate','')
        if reg_date and 'T' in reg_date: reg_date = reg_date.split('T')[0]
        last_decision = ''
        for inst in reversed(case.get('Instances',[])):
            if inst.get('FinalDocument'): last_decision = inst['FinalDocument']; break
        card_id = case.get('CaseId','')
        lines = [f"⚖️ *Дело {case_number}*\n"]
        if court: lines.append(f"⚡ *Суд:* {court}")
        if judge: lines.append(f"⚡ *Судья:* {judge}")
        if reg_date: lines.append(f"⚡ *Дата:* {reg_date}")
        if plaintiffs: lines.append(f"⚡ *Истец:* {'; '.join(plaintiffs)}")
        if defendants: lines.append(f"⚡ *Ответчик:* {'; '.join(defendants)}")
        if last_decision: lines.append(f"⚡ *Решение:* {last_decision}")
        if card_id: lines.append(f"\n[Открыть дело](https://kad.arbitr.ru/Card/{card_id})")
        return '\n'.join(lines)
    except Exception as e:
        return f"Error: {str(e)}"


async def cmd_start(update, context):
    await update.message.reply_text("Пришлите номер дела, например: *А18-333/2025*", parse_mode='Markdown')


async def handle_message(update, context):
    text = update.message.text.strip()
    match = CASE_PATTERN.search(text)
    if match:
        case_number = re.sub(r'^[Aa]', 'А', match.group(0))
        await update.message.reply_text(f"Ищу *{case_number}*...", parse_mode='Markdown')
        try:
            data = search_kad(case_number)
            resp = format_case_info(data, case_number)
            await update.message.reply_text(resp, parse_mode='Markdown', disable_web_page_preview=True)
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {str(e)}")
    else:
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(model="claude-opus-4-6", max_tokens=1024,
                system="Ты помощник юриста. Отвечай кратко на русском.",
                messages=[{"role": "user", "content": text}])
            await update.message.reply_text(msg.content[0].text)
        except Exception as e:
            await update.message.reply_text("Пришлите номер дела в формате *А18-333/2025*", parse_mode='Markdown')


def run_bot():
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)


def main():
    if not TELEGRAM_TOKEN: raise ValueError("TELEGRAM_TOKEN not set!")
    if not ANTHROPIC_API_KEY: raise ValueError("ANTHROPIC_API_KEY not set!")
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port)


if __name__ == '__main__':
    main()
