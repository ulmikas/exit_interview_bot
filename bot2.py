import os
import logging
from typing import Dict, Optional
import sqlite3
import json
from datetime import datetime
from openai import OpenAI

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

json_schema = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "Ответ на заданный вопрос"},
        "is_enough": {"type": "string", "enum": ["да", "нет"], "description": "Оцени, достаточно ли информации в ответе, чтобы полностью ответить на вопрос пользователя."},
        "explanation": {"type": "string", "description": "Краткое объяснение, почему ответ считается достаточным или недостаточным."}
    },
    "required": ["answer", "is_enough", "explanation"]
}

# Настройки бота
BOT_TOKEN = '7940286497:AAEd3jTyA8bu3N4pmDcz8qYz49eJvDs_LVg'
OPENROUTER_API_KEY = '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'
# OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1"

# Инициализация клиента OpenAI
client = OpenAI(
    api_key='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', # This should ideally be an environment variable
    base_url="https://openrouter.ai/api/v1",
)

# Состояния для ConversationHandler
START, INTERVIEW, END = range(3)

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect("interviews.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS interviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT,
        start_time TEXT NOT NULL,
        end_time TEXT,
        dialog TEXT NOT NULL,
        summary TEXT
    )
    """)
    conn.commit()
    conn.close()

init_db()

class InterviewManager:
    def __init__(self):
        self.active_interviews: Dict[int, Dict] = {}  # {user_id: interview_data}




    def start_interview(self, user_id: int, username: str):
        self.active_interviews[user_id] = {
            "start_time": datetime.now().isoformat(),
            "messages": [
                {
                    "role": "system",
                    "content": f"""Отвечай на вопросы пользователя в JSON формате, строго соответствующем следующей схеме:                      
{json.dumps(json_schema, indent=2, ensure_ascii=False)}
Твоя задача - не только дать ответ, но и оценить его полноту.
Начни с сообщения: 
Здравствуйте! Меня зовут Александр, я HR-специалист нашей компании. 
Спасибо, что согласились поделиться своим мнением в рамках заключительного интервью. 
Я знаю, что вы приняли решение покинуть нашу компанию. Мне бы очень хотелось узнать о вашем опыте работы у нас, услышать ваши мысли и пожелания. "         
Задача интервью - понять причины увольнения, получить обратную связь 
о работе компании и пожелания сотрудника. Будь вежливым, но кратким, задавай 
вопросы по одному и адаптируйся к ответам сотрудника. Старайся следовать сценарию: 
главный фактор, других факторах (до трёх), оффер, ФИО руководителя, отношения с непосредственным руководителем, 
психологический климат, профессиональное развитие, что стоит изменить.
Если поймешь что пользователь не желает продолжать заверши опрос."""
                }
            ],
            "username": username,
            "summary": None
        }

    def add_message(self, user_id: int, role: str, content: str):
        
        if user_id in self.active_interviews:
            self.active_interviews[user_id]["messages"].append({
                "role": role,
                "content": content
            })
                

    def end_interview(self, user_id: int):
        if user_id in self.active_interviews:
            interview = self.active_interviews[user_id]
            interview["end_time"] = datetime.now().isoformat()
            
            # Сохраняем в базу данных
            self.save_to_db(user_id)
            
            # Удаляем из активных интервью
            return self.active_interviews.pop(user_id)
        return None

    def save_to_db(self, user_id: int):
        if user_id not in self.active_interviews:
            return

        interview = self.active_interviews[user_id]
        conn = sqlite3.connect("interviews.db")
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT INTO interviews (user_id, username, start_time, end_time, dialog, summary)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            interview["username"],
            interview["start_time"],
            interview.get("end_time"),
            json.dumps(interview["messages"], ensure_ascii=False),
            interview.get("summary", "")
        ))
        
        conn.commit()
        conn.close()

interview_manager = InterviewManager()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info(f"Пользователь {user.id} начал взаимодействие с ботом.")
    
    keyboard = [
        [InlineKeyboardButton("Начать интервью", callback_data="start_interview")],
        [InlineKeyboardButton("Отмена", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Привет! Я бот для проведения exit interview.\n\n"
        "Я задам вам несколько вопросов о вашем опыте работы в компании "
        "и причинах увольнения. Ваши ответы помогут улучшить условия "
        "работы для других сотрудников.\n\n"
        "Нажмите 'Начать интервью', когда будете готовы.",
        reply_markup=reply_markup
    )
    
    return START

async def handle_start_interview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    interview_manager.start_interview(user.id, user.username)
    
    # Получаем первый вопрос от ИИ
    response = get_ai_response(user.id)
    interview_manager.add_message(user.id, "assistant", response)
    
    await query.edit_message_text(response)
    
    return INTERVIEW

async def handle_interview_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    answer = update.message.text
    
    # Сохраняем ответ пользователя
    interview_manager.add_message(user.id, "user", answer)
    
    # Получаем следующий вопрос от ИИ
    response = get_ai_response(user.id)
    interview_manager.add_message(user.id, "assistant", response)
    
    await update.message.reply_text(response)
    
    return INTERVIEW

async def end_interview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    interview_data = interview_manager.end_interview(user.id)
    
    if interview_data:
        # Генерируем итоговый отчет
        summary = await generate_interview_summary(interview_data["messages"])
        interview_data["summary"] = summary
        
        # Сохраняем с итоговым отчетом
        conn = sqlite3.connect("interviews.db")
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE interviews SET summary = ? WHERE user_id = ? AND end_time = ?
        """, (summary, user.id, interview_data["end_time"]))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            "Спасибо за ваши ответы! Интервью завершено.\n\n"
            f"Итоговый отчет:\n{summary}"
        )
    else:
        await update.message.reply_text("Интервью не было активно.")
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.callback_query.from_user
    interview_manager.end_interview(user.id)
    
    await update.callback_query.edit_message_text("Интервью отменено.")
    return ConversationHandler.END

def get_ai_response(user_id: int) -> str:
    if user_id not in interview_manager.active_interviews:
        return "Извините, произошла ошибка. Интервью не найдено."
    
    messages = interview_manager.active_interviews[user_id]["messages"]
    
    # headers = {
    #     "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    #     "Content-Type": "application/json"
    # }
    
    # payload = {
    #     "model": "anthropic/claude-3-opus",  # Можно изменить на другую модель
    #     "messages": messages
    # }
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=messages,
            temperature=0.7
        )
        
        logger.info(f"response: {response}")
        
        return response.choices[0].message.content
        
        # async with httpx.AsyncClient() as client:
        #     response = await client.post(
        #         OPENROUTER_API_URL,
        #         headers=headers,
        #         json=payload,
        #         timeout=30.0
        #     )
        #     response.raise_for_status()
        #     data = response.json()
            
        #     return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Ошибка при запросе к OpenRouter: {e}")
        return "Извините, произошла ошибка при обработке вашего ответа. Пожалуйста, попробуйте еще раз."

async def generate_interview_summary(messages: list) -> str:
    dialog = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "anthropic/claude-3-opus",
        "messages": [
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
        ]
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OPENROUTER_API_URL,
                headers=headers,
                json=payload,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Ошибка при генерации отчета: {e}")
        return "Не удалось сгенерировать полный отчет. Пожалуйста, проверьте диалог вручную."

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            START: [
                CallbackQueryHandler(handle_start_interview, pattern="^start_interview$"),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ],
            INTERVIEW: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_interview_answer),
                CommandHandler("end", end_interview)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    application.add_handler(conv_handler)
    
    application.run_polling()

if __name__ == "__main__":
    import httpx
    main()