from flask import Flask, jsonify, request
from flask_cors import CORS
from models import SurveyResponse, SessionLocal
from sqlalchemy import distinct
import json

app = Flask(__name__)
CORS(app)  # Разрешает все origins (для разработки)

@app.route('/dialogs', methods=['GET'])
def get_dialog_ids():
    db_session = SessionLocal()
    unique_users = db_session.query(distinct(SurveyResponse.user_id)).all()
    users_list = [u[0] for u in unique_users]
    db_session.close()
    return jsonify(users_list)
  
@app.route('/dialogs/<int:user_id>', methods=['GET'])
def get_dialog_by_user_id(user_id):
    db_session = SessionLocal()
    response = db_session.query(SurveyResponse).filter(SurveyResponse.user_id == user_id).order_by(SurveyResponse.id.desc()).first()
    
    dialog_data = {
        'id': response.id,
        'user_id': response.user_id,
        'username': response.username,
        'dialog': json.loads(response.dialog),
        'summary': response.summary,
        'start_time': response.start_time,
        'end_time': response.end_time
    }
    
    return jsonify(dialog_data)
    # dialog_history = []
    # for resp in responses:
    #     dialog_history.append({
    #         'id': resp.id,
    #         'user_id': resp.user_id,
    #         'username': resp.username,
    #         'dialog': resp.dialog,
    #         'summary': resp.summary,
    #         'start_time': resp.start_time,
    #         'end_time': resp.end_time
    #     })
    # db_session.close()
    # return jsonify(dialog_history)


if __name__ == "__main__":
    app.run(debug=True)