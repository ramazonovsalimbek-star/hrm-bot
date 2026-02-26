print("=== QUIZ + TERMS (ONE BOT.PY) RUNNING ===")

import os
import json
import random
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes





# ==========================================================
# ОБЩИЕ НАСТРОЙКИ
# ==========================================================
BOT_TOKEN = "8087665173:AAGOGdWuyD4PvOVuob_CVD2Pv5qu4W6pNSc"
CHANNEL_CHAT_ID = "@hrm_quiz"  # канал (или -100... для приватного)

if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN. Задайте переменную окружения BOT_TOKEN (новый токен).")


# ==========================================================
# БЛОК 1: QUIZ (ТЕСТЫ)
# ==========================================================
QUESTIONS_FILE = "questions.json"
POST_QUIZ_EVERY_SECONDS = 5400  # тесты: раз в 90 минут

QUESTIONS_NO_REPEAT_CYCLE = True
_questions_queue = []
_questions_idx = 0
_last_question_key = None


def load_questions():
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise ValueError("questions.json должен быть списком (не пустой).")
    return data

def question_unique_key(q: dict) -> str:
    """
    Делаем "ключ" вопроса по тексту.
    У вас бывает q или question — поддерживаем оба.
    lower() — чтобы 'Что?' и 'что?' считались одинаковыми.
    """
    return (q.get("q") or q.get("question") or "").strip().lower()


def pick_next_question() -> dict:
    """
    Отдаёт следующий вопрос:
    - без повторов, пока не пройдём весь список
    - не повторяет один и тот же вопрос подряд
    """
    global _questions_queue, _questions_idx, _last_question_key

    questions = load_questions()

    # Если отключите режим цикла — будет обычный рандом
    if not QUESTIONS_NO_REPEAT_CYCLE:
        return random.choice(questions)

    # Если очередь пустая или закончилась — пересоздаём и перемешиваем
    if not _questions_queue or _questions_idx >= len(_questions_queue):
        _questions_queue = questions[:]      # копия списка
        random.shuffle(_questions_queue)     # перемешали
        _questions_idx = 0                   # начинаем сначала

    # Берём следующий элемент, но проверяем, чтобы не совпал с прошлым
    # Обычно срабатывает сразу с первой попытки.
    attempts = 0
    while attempts < len(_questions_queue):
        q = _questions_queue[_questions_idx]
        _questions_idx += 1

        key = question_unique_key(q)

        # Если не повтор подряд — возвращаем
        if key and key != _last_question_key:
            _last_question_key = key
            return q

        attempts += 1

        # Если дошли до конца очереди — снова перемешаем и продолжим
        if _questions_idx >= len(_questions_queue):
            _questions_queue = questions[:]
            random.shuffle(_questions_queue)
            _questions_idx = 0

    # fallback: если вдруг данные кривые (пустые тексты)
    q = random.choice(questions)
    _last_question_key = question_unique_key(q)
    return q



def convert_options(q: dict):
    """
    Поддерживает 2 формата из вашего questions.json:
    1) options = {"A": "...", "B": "...", ...}, answer = "B"
    2) options = ["...", "...", ...], answer = 1  (или correct_index)
    """
    opts = q.get("options")

    # Формат 2: список вариантов
    if isinstance(opts, list):
        if "correct_index" in q:
            correct_index = int(q["correct_index"])
        else:
            correct_index = int(q.get("answer"))  # у вас answer = число
        return opts, correct_index

    # Формат 1: словарь A/B/C/D/E
    if isinstance(opts, dict):
        order = ["A", "B", "C", "D", "E"]
        options_list = [opts[k] for k in order if k in opts]

        answer_letter = (q.get("answer") or "").strip().upper()
        if answer_letter not in order:
            raise ValueError("В формате A/B/C/D/E поле answer должно быть буквой A..E")

        correct_index = order.index(answer_letter)
        return options_list, correct_index

    raise ValueError("options должен быть list или dict")



async def job_post_quiz(context: ContextTypes.DEFAULT_TYPE):
    """Автопостинг теста (quiz-poll) в канал. Поддерживает оба формата вопросов."""
        q = pick_next_question()


    # Вопрос может быть в поле q или question
    question_body = (q.get("q") or q.get("question") or "").strip()
    if not question_body:
        raise ValueError("Вопрос должен содержать поле 'q' или 'question'")

    # Заголовок: lesson или category
    if "lesson" in q:
        header = f"📚 Урок {q.get('lesson','?')}\n\n"
    elif "category" in q:
        header = f"📚 {q.get('category','Тест')}\n\n"
    else:
        header = "📚 Тест\n\n"

    question_text = header + question_body

    options_list, correct_index = convert_options(q)

    await context.bot.send_poll(
        chat_id=CHANNEL_CHAT_ID,
        question=question_text,
        options=options_list,
        type="quiz",
        correct_option_id=correct_index,
        is_anonymous=True,
        allows_multiple_answers=False
    )



async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручная команда: опубликовать следующий тест."""
    await job_post_quiz(context)
    if update.message:
        await update.message.reply_text("✅ Quiz опубликован.")


# ==========================================================
# БЛОК 2: TERMS (ТЕРМИНЫ)
# ==========================================================
TERMS_FILE = "terms.json"
POST_TERM_EVERY_SECONDS = 9000  # термины: раз в 150 минут

# Чтобы термины не повторялись подряд — можно включить очередь:
TERMS_NO_REPEAT_CYCLE = True
_terms_queue = []
_terms_idx = 0


def load_terms():
    with open(TERMS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise ValueError("terms.json должен быть списком (не пустой).")
    return data


def format_term_post(item: dict) -> str:
    """Идеально логичный формат: инсайт берём из JSON (не рандом)."""
    section = item.get("section", "").strip()
    term = item.get("term", "").strip()
    definition = item.get("definition", "").strip()
    insight = item.get("insight", "").strip()

    if not (section and term and definition and insight):
        raise ValueError("Каждый термин должен иметь section, term, definition и insight")

    emoji_map = {
        "Кибербезопасность": "🔐",
        "Данные и технологии": "📊",
        "Облачные технологии": "☁️",
        "Искусственный интеллект": "🤖",
        "Финтех": "💳",
        "Цифровая экономика": "📈",
        "Цифровое государство": "🏛",
        "Стартапы и инновации": "🚀",
        "Стартапы и инвестиции": "🚀",
        "IT-рынок и работа": "💼",
        "Экспорт IT-услуг": "🌍",
        "BPO и сервисы": "🎧",
        "Платформенная экономика": "📱",
        "Электронная коммерция": "🛒"
    }

    emoji = emoji_map.get(section, "💡")

    return (
        f"{emoji} *{section}*\n\n"
        f"🔎 *Термин:* {term}\n\n"
        f"{definition}\n\n"
        f"{insight}\n"
        f"📌 #DigitalEconomy #DigitalUzbekistan #ITPark"
    )


def pick_next_term() -> dict:
    """Берём термин либо рандомно, либо циклом без повторов."""
    global _terms_queue, _terms_idx

    terms = load_terms()

    if not TERMS_NO_REPEAT_CYCLE:
        return random.choice(terms)

    # цикл без повторов: перемешали -> идём по очереди -> снова перемешали
    if not _terms_queue or _terms_idx >= len(_terms_queue):
        _terms_queue = terms[:]
        random.shuffle(_terms_queue)
        _terms_idx = 0

    item = _terms_queue[_terms_idx]
    _terms_idx += 1
    return item


async def job_post_term(context: ContextTypes.DEFAULT_TYPE):
    """Автопостинг термина в канал."""
    item = pick_next_term()
    text = format_term_post(item)

    await context.bot.send_message(
        chat_id=CHANNEL_CHAT_ID,
        text=text,
        parse_mode="Markdown"
    )


async def cmd_term(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручная команда: опубликовать термин."""
    await job_post_term(context)
    if update.message:
        await update.message.reply_text("✅ Термин опубликован.")


# ==========================================================
# ДОП КОМАНДЫ
# ==========================================================
async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("✅ Бот работает. Команды: /next (quiz), /term (термин)")


# ==========================================================
# MAIN
# ==========================================================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("next", cmd_next))
    app.add_handler(CommandHandler("term", cmd_term))

    # Две независимые задачи — параллельно и без конфликтов
    app.job_queue.run_repeating(job_post_quiz, interval=POST_QUIZ_EVERY_SECONDS, first=10, name="quiz_job")
    app.job_queue.run_repeating(job_post_term, interval=POST_TERM_EVERY_SECONDS, first=20, name="term_job")

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()




