import sqlite3, json, requests
from telegram import Update, InlineKeyboardButton, KeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from openai import OpenAI
from datetime import datetime
import logging


# Токены и ключи для работы с Telegram и OpenRouter
TELEGRAM_BOT_TOKEN = '7940286497:AAEd3jTyA8bu3N4pmDcz8qYz49eJvDs_LVg'
OPENROUTER_API_KEY = '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'
DATABASE_NAME = 'interviews.db'

# Индикаторы активности опроса
ACTIVE_SESSION = True
INACTIVE_SESSION = False

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Определяем схему ожидаемого JSON ответа
json_schema = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "Ответ на заданный вопрос"},
        "is_enough": {"type": "string", "enum": ["да", "нет"], "description": "Оцени, достаточно ли информации в ответе, чтобы полностью ответить на вопрос пользователя."},
        "explanation": {"type": "string", "description": "Краткое объяснение, почему ответ считается достаточным или недостаточным."}
    },
    "required": ["answer", "is_enough", "explanation"]
}

# Получаем ключ из переменной окружения
client = OpenAI(
    api_key='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', # This should ideally be an environment variable
    base_url="https://openrouter.ai/api/v1",
)

# Формируем системный промпт
system_prompt = f"""
Ответь на вопрос пользователя в JSON формате, строго соответствующем следующей схеме:

```json
{json.dumps(json_schema, indent=2, ensure_ascii=False)}
```
Задача интервью - понять причины увольнения, получить обратную связь 
о работе компании и пожелания сотрудника. Будь вежливым, но кратким, задавай 
вопросы по одному и адаптируйся к ответам сотрудника. Старайся следовать сценарию: 
главный фактор, других факторах (до трёх), оффер, ФИО руководителя, отношения с непосредственным руководителем, 
психологический климат, профессиональное развитие, что стоит изменить. 
Если поймешь что пользователь не желает продолжать заверши опрос.

- Поле \"Ответ на вопрос\": Сформулируй четкий и краткий ответ на вопрос пользователя.
- Поле \"Достаточно ли ответа\": Укажи 'да', если твой ответ является исчерпывающим. Укажи 'нет', если для полного ответа требуется уточнение или дополнительная информация.
- Поле \"Объяснение\": Кратко поясни, почему ты считаешь ответ достаточным или недостаточным. Например, если ответ 'нет', укажи, какой информации не хватает.
"""



def create_database():
    conn = sqlite3.connect(DATABASE_NAME)
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    logger.info(f"Пользователь {user.id} начал взаимодействие с ботом.")
    
    keyboard = [
        [KeyboardButton(text="🔥 Начать"), KeyboardButton(text="❌ Отменить")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    # await update.message.reply_text("Добро пожаловать в опрос! Выберите действие:", reply_markup=reply_markup)
    
    # keyboard = [
    #     [InlineKeyboardButton("Начать интервью", callback_data="button_start")],
    #     [InlineKeyboardButton("Отмена", callback_data="cancel")]
    # ]
    # reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Здравствуйте! Меня зовут Александр, я HR-специалист нашей компании."
        "Спасибо, что согласились поделиться своим мнением в рамках заключительного интервью. "
        "Я знаю, что вы приняли решение покинуть нашу компанию. Мне бы очень хотелось узнать о вашем опыте работы у нас, услышать ваши мысли и пожелания.\n\n"
        "Нажмите 'Начать интервью', когда будете готовы.",
        reply_markup=reply_markup
    )
  
async def button_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает опрос после выбора кнопки 'Начать'"""
    
  
    
    await update.message.reply_text("Опиши одним–двумя абзацами главный фактор, который стал решающим в твоём решении уволиться. Почему именно он оказался критичным?")
    context.user_data['state'] = ACTIVE_SESSION
    context.user_data['answers'] = []
    context.user_data['dialog'] = []
    context.user_data['messages'] = []
    context.user_data['last_question'] = ""
    context.user_data['start_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

async def button_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Прерывает опрос и сбрасывает состояние пользователя"""
    await update.message.reply_text("Опрос отменён. Вы можете начать его заново, набрав /start")
    context.user_data.clear()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != ACTIVE_SESSION:
      return

    user_answer = update.message.text.strip()
    chat_id = str(update.effective_chat.id)
    
    
    # Добавляем последний вопрос и ответ в диалог
    last_question = context.user_data.get('last_question', '')
    context.user_data.setdefault('dialog', [])
    context.user_data['dialog'].extend([f"Бот: {last_question}", f"Пользователь: {user_answer}"])
    
    context.user_data['answers'].append(user_answer)
    
    context.user_data['messages'].append({
                "role": "assistant",
                "content": last_question
            })
    context.user_data['messages'].append({
                "role": "user",
                "content": user_answer
            })
    # next_question = generate_next_question(chat_id, context.user_data['answers'])
    
    
    # # Сохраняем предыдущий ответ
    # if not hasattr(context.user_data, 'answers'):
    #     context.user_data['answers'] = []
    # context.user_data['answers'].append(user_answer)

    # # Отправляем предыдущие ответы в OpenRouter для обработки и генерации следующего вопроса
    next_question = generate_next_question(chat_id, context.user_data['answers'])
    next_question_text = next_question['answer']
    
    print(f"next_question {next_question}")
    print(f"next_question_text {next_question_text}")

    if next_question['is_enough'] == 'да':
      await finish_survey(update, context)
    else:
      await update.message.reply_text(next_question['answer'])



def generate_next_question(employee_id, previous_answers):
    # Обновляем запрос с указанием схемы
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            *[{"role": "user", "content": answer} for answer in previous_answers]
        ],
    )

    try:
        result = json.loads(response.choices[0].message.content)
        print(json.dumps(result, indent=2, ensure_ascii=False))

        return result

    except json.JSONDecodeError:
        print("Error decoding JSON from API response:")
        print(response.choices[0].message.content)


async def finish_survey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    final_summary = '\n'.join(context.user_data.get('answers', []))
    full_dialog = '\n'.join(context.user_data.get('dialog', []))
    
    # Заполняем и сохраняем итоговую запись в базу данных
    user_id = update.effective_user.id
    username = update.effective_user.username
    start_time = context.user_data.get('start_time', '')  # Время начала опроса было установлено при старте
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    final_summary = await generate_interview_summary(context.user_data.get('messages'))
    
    print(f"!!!! {final_summary}")
    
    save_interview(user_id, username, start_time, now, full_dialog, final_summary)
    
    
    # save_to_db(str(update.effective_chat.id), context)
    
    await update.message.reply_text(f"Спасибо за участие!\nВаш опрос завершён.\nИтоговый отчет:\n\n{final_summary}")
    context.user_data['state'] = INACTIVE_SESSION
    del context.user_data['answers']

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.edit_message_text("Интервью отменено.")
    context.user_data['state'] = INACTIVE_SESSION
    await finish_survey(update, context)


def save_interview(user_id, username, start_time, end_time, dialog, summary):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO interviews2 (user_id, username, start_time, end_time, dialog, summary)
        VALUES (?, ?, ?, ?, ?, ?);
    """, (user_id, username, start_time, end_time, dialog, summary))
    conn.commit()
    conn.close()


async def generate_interview_summary(messages: str) -> str:
    dialog = "\n".join([f"{m['role']}: {m['content']}" for m in messages])

    # Обновляем запрос с указанием схемы
    response = client.chat.completions.create(
        model="anthropic/claude-3-opus",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "Проанализируй диалог exit interview и создай краткий отчет с ключевыми моментами: "
                           "1. Основные причины увольнения. "
                           "2. Критика компании/процессов. "
                           "3. Пожелания сотрудника. "
                           "4. Общий тон интервью (позитивный/нейтральный/негативный). "
                           "Отчет должен быть структурированным и информативным."
            },
            {
                "role": "user",
                "content": dialog
            }
        ],
    )

    return response.choices[0].message.content
       



if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    create_database()  # Создаем таблицу базы данных

    # Настройка обработчиков команд и сообщений
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex("^🔥 Начать$"), button_start))
    application.add_handler(MessageHandler(filters.Regex("^❌ Отменить$"), button_cancel))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("Telegram bot started...")
    application.run_polling()