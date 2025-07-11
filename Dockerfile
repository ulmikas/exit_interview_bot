# Базовый образ Python
FROM python:3.13.2-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Рабочая директория в контейнере
WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальные файлы
COPY . .

# EXPOSE 5000

# Команда для запуска приложения
CMD ["python", "bot.py"]