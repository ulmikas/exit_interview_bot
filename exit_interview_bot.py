import logging
import json
import httpx
from typing import Dict, Any
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from models import engine, session, Base, SurveyResponse, SessionLocal

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                     level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
SURVEY_IN_PROGRESS, ANSWERING_QUESTION = range(2)

        
class SurveyBot:
    def __init__(self, survey_config: Dict[str, Any]):
        self.questions = survey_config["questions"]
        self.user_sessions = {}  # Хранение сессий пользователей
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user = update.message.from_user
        user_id = user.id
        
        self.user_sessions[user_id] = {
            'answers': {},
            'current_question_index': 0,
            'user_data': {
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name
            }
        }
        
        await update.message.reply_text(
            "Добро пожаловать в опрос! Давайте начнем.\n"
            "Вы можете прервать опрос в любой момент командой /cancel.\n\n"
            "Первый вопрос:",
            reply_markup=ReplyKeyboardRemove()
        )
        
        await self.ask_question(update, context, user_id)
        return ANSWERING_QUESTION
    
    async def ask_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        session = self.user_sessions[user_id]
        question_index = session['current_question_index']
        
        if question_index >= len(self.questions):
            await self.finish_survey(update, context, user_id)
            return ConversationHandler.END
        
        question = self.questions[question_index]
        question_text = f"Вопрос {question_index + 1}/{len(self.questions)}:\n{question['text']}"
        
        if not question["required"]:
            question_text += "\n\n(Этот вопрос необязательный)"
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=question_text
        )
    
    async def handle_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_id = update.message.from_user.id
        session = self.user_sessions.get(user_id)
        
        if not session:
            await update.message.reply_text("Сессия опроса не найдена. Начните заново с /start.")
            return ConversationHandler.END
        
        question = self.questions[session['current_question_index']]
        answer = update.message.text
        
        if question["required"] and not answer.strip():
            await update.message.reply_text("Это обязательный вопрос, пожалуйста, ответьте на него.")
            return ANSWERING_QUESTION




        prompt = {
          "model": "anthropic/claude-3-sonnet",  # Можно выбрать любую модель
          "messages": [
              {"role": "system", "content": "Ты - профессиональный интервьюер, который задает глубокие вопросы."},
              {"role": "user", "content": f"""
                  История диалога:
                  {question["text"]}
                  
                  Последний ответ пользователя: {answer}
                  
                  Проанализируй ответ и скажи закончить ли диалог, если стоит продолжить то что спросить далее:
              """}
          ],
          "temperature": 0.7,
          "max_tokens": 150
        }

        headers = {
          "Authorization": f"Bearer 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"
        }


        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=prompt,
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            
            logger.info(f"Data {data}")
            
            return data['choices'][0]['message']['content'].strip()






        
        # Сохраняем ответ в БД
        self._save_to_db(user_id, question["text"], answer)
        
        session['answers'][question["id"]] = answer
        session['current_question_index'] += 1
        
        await self.ask_question(update, context, user_id)
        return ANSWERING_QUESTION if session['current_question_index'] < len(self.questions) else ConversationHandler.END
      
    def _save_to_db(self, user_id: int, question: str, answer: str):
        """Сохраняет ответ пользователя в базу данных"""
        try:
            db = SessionLocal()
            db.add(SurveyResponse(
                user_id=user_id,
                question=question,
                answer=answer
            ))
            db.commit()
            logger.info(f"Ответ сохранен в БД: user_id={user_id}, question={question}")
        except Exception as e:
            db.rollback()
            logger.error(f"Ошибка при сохранении в БД: {e}")
        finally:
            db.close()
            
    async def finish_survey(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        session = self.user_sessions[user_id]
        
        # Формируем отчет с ответами
        report = "Спасибо за участие в опросе! Вот ваши ответы:\n\n"
        for q in self.questions:
            answer = session['answers'].get(q["id"], "(нет ответа)")
            report += f"❓ {q['text']}\n📝 Ответ: {answer}\n\n"
        
        # Отправляем отчет пользователю
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=report
        )
        
        # Здесь можно добавить сохранение ответов в базу данных или файл
        logger.info(f"User {user_id} completed survey. Answers: {session['answers']}")
        
        # Удаляем сессию пользователя
        del self.user_sessions[user_id]
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_id = update.message.from_user.id
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]
        
        await update.message.reply_text(
            "Опрос прерван. Если хотите начать заново, используйте /start.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

# Загрузка JSON из файла
def load_survey_config(file_path: str) -> Dict[str, Any]:
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error {context.error}")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Произошла ошибка. Пожалуйста, попробуйте снова."
    )

def main() -> None:
    try:
        # Загружаем конфиг опроса
        config = load_survey_config("exit_interview_questions.json")  # Укажите правильный путь к файлу
        bot = SurveyBot(config)
        
        # Создаем Application и передаем токен бота
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Настраиваем обработчики команд
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', bot.start)],
            states={
                ANSWERING_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_answer)]
            },
            fallbacks=[CommandHandler('cancel', bot.cancel)],
            allow_reentry=True
        )
        
        application.add_handler(conv_handler)
        application.add_error_handler(error_handler)
        
        # Запускаем бота
        print("Бот запущен...")
        application.run_polling()
    
    except FileNotFoundError:
        logger.error("Ошибка: файл с конфигурацией опроса не найден.")
    except json.JSONDecodeError:
        logger.error("Ошибка: файл с конфигурацией опроса имеет неверный формат.")
    except KeyError:
        logger.error("Ошибка: в конфигурации опроса отсутствуют необходимые поля.")
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")

if __name__ == '__main__':
    main()
