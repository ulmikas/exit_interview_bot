from flask import Flask, jsonify, abort
from models import SurveyResponse, SessionLocal
from sqlalchemy import distinct
import json
import logging

app = Flask(__name__)
logger = logging.getLogger(__name__)


def parse_dialog_field(dialog_json):
    """Безопасно десериализует JSON из поля dialog."""
    if not dialog_json:
        return {}
    try:
        return json.loads(dialog_json)
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка десериализации JSON: {e}")
        raise


@app.route('/dialogs', methods=['GET'])
def get_dialog_ids():
    """Возвращает список всех уникальных ID пользователей."""
    with SessionLocal() as db_session:
        user_ids = user_ids = (
            db_session.query(SurveyResponse.user_id)
            .filter(SurveyResponse.user_id.isnot(None))
            .distinct()
            .all()
        )

    return jsonify([user_id for (user_id,) in user_ids])


@app.route('/dialogs/<int:user_id>', methods=['GET'])
def get_dialog_by_user_id(user_id):
    """Возвращает данные диалога пользователя по его ID."""
    with SessionLocal() as db_session:
        response = (
            db_session.query(SurveyResponse)
            .filter(SurveyResponse.user_id == user_id)
            .order_by(SurveyResponse.id.desc())
            .first()
        )

        if not response:
            abort(404, description=f"User with ID {user_id} not found")

        dialog_content = parse_dialog_field(response.dialog)

        dialog_data = {
            'id': response.id,
            'user_id': response.user_id,
            'username': response.username,
            'dialog': dialog_content,
            'summary': response.summary,
            'start_time': response.start_time,
            'end_time': response.end_time
        }

    return jsonify(dialog_data)


if __name__ == "__main__":
    app.run(debug=True)
