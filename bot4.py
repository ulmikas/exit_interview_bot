import sqlite3
import json
import logging
from datetime import datetime

from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI

# --- КОНФИГУРАЦИЯ И КОНСТАНТЫ ---

# Загрузка токенов и ключей
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

# Индикаторы состояния сессии
ACTIVE_SESSION = True
INACTIVE_SESSION = False

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Клиент OpenAI/OpenRouter
client = OpenAI(
    api_key=config['OPENROUTER_API_KEY'],
    base_url="https://openrouter.ai/api/v1",
)

# СПИСОК ВОПРОСОВ ДЛЯ ИНТЕРВЬЮ (теперь в коде)
QUESTIONS = [
    "1. Опиши одним–двумя абзацами главный фактор, который стал решающим в твоём решении уволиться. Почему именно он оказался критичным?",
    "2. Расскажи о других факторах (до трёх), которые также повлияли на твоё решение. Чем они были для тебя важны?",
    "3. Есть ли у тебя в данный момент активный оффер? Если да, расскажи от какой компании и какие условия тебя привлекли. Если нет — почему?",
    "4. Укажи ФИО руководителя, который ставил тебе задачи и давал обратную связь.",
    "5. Как складывались твои отношения с непосредственным руководителем? Приведи примеры удачных или проблемных взаимодействий.",
    "6. Опиши психологический климат в своём подразделении: что помогало и что мешало комфортной работе?",
    "7. Как ты оцениваешь свои возможности профессионального развития внутри компании? Какие барьеры или, наоборот, возможности ты видел?",
    "8. Насколько, по твоему опыту, компания заботилась о благополучии сотрудников? Приведи примеры поддержки или её отсутствия.",
    "9. Что, по твоему мнению, стоит изменить, внедрить или улучшить в процессах, команде или компании в целом? Дай конкретные предложения."
]

# --- ФУНКЦИИ БАЗЫ ДАННЫХ ---

def create_database():
    """Создает таблицу в базе данных, если она не существует."""
    conn = sqlite3.connect(config['DATABASE_NAME'])
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS interviews2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            start_time TEXT NOT NULL,
            end_time TEXT,
            dialog TEXT NOT NULL,
            summary TEXT
        );
    ''')
    conn.commit()
    conn.close()

def save_interview(user_id, username, start_time, end_time, dialog, summary):
    """Сохраняет результаты интервью в базу данных."""
    conn = sqlite3.connect(config['DATABASE_NAME'])
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO interviews2 (user_id, username, start_time, end_time, dialog, summary)
        VALUES (?, ?, ?, ?, ?, ?);
    """, (user_id, username, start_time, end_time, dialog, summary))
    conn.commit()
    conn.close()
    logger.info(f"Интервью для пользователя {user_id} сохранено в базу данных.")

# --- ФУНКЦИИ ДЛЯ РАБОТЫ С МОДЕЛЬЮ ---

async def generate_interview_summary(messages: list) -> str:
    """Генерирует итоговый отчет по диалогу с помощью LLM."""
    # Преобразуем список словарей в одну строку для промпта
    dialog_text = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in messages])

    system_prompt_summary = (
        "Ты — HR-аналитик. Проанализируй следующий диалог exit-интервью и создай краткий, структурированный отчет. "
        "В отчете должны быть четко выделены следующие пункты:\n"
        "1. Основные причины увольнения (главные и второстепенные).\n"
        "2. Обратная связь о руководителе и команде.\n"
        "3. Обратная связь о процессах, развитии и благополучии в компании.\n"
        "4. Конкретные предложения сотрудника по улучшению.\n"
        "5. Общий тон интервью (например, конструктивный, негативный, нейтральный).\n"
        "Отчет должен быть написан в безличном, профессиональном стиле."
    )

    try:
        response = client.chat.completions.create(
            model="anthropic/claude-3-sonnet", # Используем Sonnet, он дешевле и быстрее Opus для таких задач
            messages=[
                {"role": "system", "content": system_prompt_summary},
                {"role": "user", "content": dialog_text}
            ],
            max_tokens=1024,
        )
        summary = response.choices[0].message.content
        logger.info("Итоговый отчет успешно сгенерирован.")
        return summary
    except Exception as e:
        logger.error(f"Ошибка при генерации отчета: {e}")
        return "Не удалось сгенерировать итоговый отчет из-за ошибки."

# --- ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ ТЕЛЕГРАМ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start. Предлагает начать интервью."""
    user = update.message.from_user
    logger.info(f"Пользователь {user.id} ({user.username}) начал взаимодействие с ботом.")
    
    keyboard = [[KeyboardButton(text="🔥 Начать"), KeyboardButton(text="❌ Отменить")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        "Здравствуйте! Меня зовут Игорь, я помощник HR-специалистов Ростелеком ИТ. Я знаю, что вы приняли решение покинуть нашу компанию.\n\n" 
        "По статистике найм бывших сотрудников доходит до 20-25%, так как специалисты часто уходят за новым опытом, но потом возвращаются. Мне бы очень хотелось узнать о вашем опыте работы у нас, услышать ваши мысли и пожелания для изменений компании в будущем. Чтобы когда вы вернетесь к нам на работу мы стали лучше.\n\n"
        "Нажмите 'Начать интервью', когда будете готовы.",
        reply_markup=reply_markup
    )

async def button_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает опрос после нажатия кнопки 'Начать'."""
    logger.info(f"Пользователь {update.effective_user.id} начал интервью.")
    
    # Инициализация состояния пользователя
    context.user_data['state'] = ACTIVE_SESSION
    context.user_data['start_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    context.user_data['question_index'] = 0
    
    # Задаем первый вопрос
    first_question = QUESTIONS[0]
    context.user_data['messages'] = [{"role": "assistant", "content": first_question}]
    
    await update.message.reply_text(first_question)

async def button_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет опрос и сбрасывает состояние."""
    logger.info(f"Пользователь {update.effective_user.id} отменил интервью.")
    await update.message.reply_text("Опрос отменён. Вы можете начать его заново, набрав /start")
    context.user_data.clear()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ответы пользователя и задает следующие вопросы."""
    if context.user_data.get('state') != ACTIVE_SESSION:
        return

    user_answer = update.message.text.strip()
    
    # Сохраняем ответ пользователя
    context.user_data.setdefault('messages', []).append({"role": "user", "content": user_answer})
    
    # Увеличиваем индекс вопроса
    current_index = context.user_data.get('question_index', 0)
    next_index = current_index + 1
    
    # Проверяем, есть ли еще вопросы
    if next_index < len(QUESTIONS):
        # Задаем следующий вопрос
        next_question = QUESTIONS[next_index]
        await update.message.reply_text(next_question)
        
        # Сохраняем вопрос бота и обновляем индекс
        context.user_data['messages'].append({"role": "assistant", "content": next_question})
        context.user_data['question_index'] = next_index
    else:
        # Вопросы закончились, завершаем опрос
        await finish_survey(update, context)

async def finish_survey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает опрос, генерирует отчет и сохраняет данные."""
    logger.info(f"Завершение интервью для пользователя {update.effective_user.id}.")
    
    await update.message.reply_text("Спасибо за ваши ответы! Сейчас я подготовлю итоговый отчет...")

    messages = context.user_data.get('messages', [])
    dialog_for_db = json.dumps(messages, ensure_ascii=False, indent=2)
    
    # Генерируем итоговый отчет
    final_summary = await generate_interview_summary(messages)
    
    # Сохраняем все в базу данных
    user_id = update.effective_user.id
    username = update.effective_user.username
    start_time = context.user_data.get('start_time', '')
    end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    save_interview(user_id, username, start_time, end_time, dialog_for_db, final_summary)
    
    # Отправляем пользователю сообщение о завершении и сам отчет
    await update.message.reply_text(
        f"Спасибо за участие!\nВаш опрос завершён.\n\n--- Итоговый отчет ---\n\n{final_summary}"
    )
    
    # Очищаем состояние пользователя
    context.user_data.clear()

# --- ЗАПУСК БОТА ---

if __name__ == '__main__':
    application = ApplicationBuilder().token(config['TELEGRAM_BOT_TOKEN']).build()

    create_database()

    # Настройка обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex("^🔥 Начать$"), button_start))
    application.add_handler(MessageHandler(filters.Regex("^❌ Отменить$"), button_cancel))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("Telegram бот запущен...")
    application.run_polling()