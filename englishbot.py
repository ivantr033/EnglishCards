import telebot
from telebot import types
import psycopg2
import random
import atexit
from config import TELEGRAM_TOKEN, DB_NAME, DB_USER, DB_PASSWORD, DB_HOST

bot = telebot.TeleBot(TELEGRAM_TOKEN)

conn = psycopg2.connect(
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST
)
cursor = conn.cursor()


def create_table():
    cursor.execute("""
       CREATE TABLE IF NOT EXISTS users (
         user_id SERIAL PRIMARY KEY,
         telegram_id BIGINT UNIQUE NOT NULL,
         username TEXT NOT NULL
       );
    """)
    cursor.execute("""
       CREATE TABLE IF NOT EXISTS words (
           word_id SERIAL PRIMARY KEY,
           word_ru TEXT NOT NULL,
           word_en TEXT NOT NULL
       );
    """)
    cursor.execute("""
       CREATE TABLE IF NOT EXISTS user_words (
          user_word_id SERIAL PRIMARY KEY,
          user_id INTEGER REFERENCES users (user_id) ON DELETE CASCADE,
          word_id INTEGER REFERENCES words (word_id) ON DELETE CASCADE
       );
    """)
    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM words")
    q_words = cursor.fetchone()[0]
    if q_words < 10:
        base_words = [
            ('книга', 'book'),
            ('собака', 'dog'),
            ('яблоко', 'apple'),
            ('карандаш', 'pencil'),
            ('дом', 'house'),
            ('цветок', 'flower'),
            ('кот', 'cat'),
            ('машина', 'car'),
            ('школа', 'school'),
            ('учитель', 'teacher')
        ]

        for ru, en in base_words:
            cursor.execute("SELECT 1 FROM words WHERE word_ru=%s AND word_en=%s", (ru, en))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO words (word_ru, word_en) VALUES (%s, %s)", (ru, en))
        conn.commit()

create_table()


def register_user(message):
    telegram_id = message.from_user.id
    username = message.from_user.username
    cursor.execute("SELECT * FROM users WHERE telegram_id=%s", (telegram_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (telegram_id, username) VALUES (%s, %s)", (telegram_id, username))
        conn.commit()

@atexit.register
def close_db():
    try:
        cursor.close()
        conn.close()
    except:
        pass


def main_menu(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True) # InlineKeyboard
    markup.row('Пройти тест', 'Добавить слово')
    markup.row('Удалить слово')
    bot.send_message(chat_id, "Выберите действие:", reply_markup=markup)


@bot.message_handler(commands=['start'])
def start(message):
    register_user(message)
    bot.send_message(message.chat.id, f"Привет, {message.chat.first_name}! Добро пожаловать в EnglishCard!") # message.from_user.username
    main_menu(message.chat.id)


@bot.message_handler(func=lambda message: True)
def menu_handler(message):
    if message.text == 'Пройти тест':
        quiz(message)
    elif message.text == 'Добавить слово':
        msg = bot.send_message(message.chat.id,
                               "Введите слово на русском и английском через запятую (например: яблоко,apple)")
        bot.register_next_step_handler(msg, process_add)
    elif message.text == 'Удалить слово':
        delete_word(message)
    else:
        bot.send_message(message.chat.id, "Выберите действие из меню.")
        main_menu(message.chat.id)


def process_add(message):
    try:
        ru, en = map(str.strip, message.text.split(','))
        telegram_id = message.from_user.id

        cursor.execute("INSERT INTO words (word_ru, word_en) VALUES (%s, %s) RETURNING word_id", (ru, en))
        word_id = cursor.fetchone()[0]

        cursor.execute("SELECT user_id FROM users WHERE telegram_id=%s", (telegram_id,))
        user_id = cursor.fetchone()[0]

        cursor.execute("INSERT INTO user_words (user_id, word_id) VALUES (%s, %s)", (user_id, word_id))
        conn.commit()

        cursor.execute("SELECT COUNT(*) FROM user_words WHERE user_id=%s", (user_id,))
        count = cursor.fetchone()[0]

        bot.send_message(message.chat.id, f"Слово добавлено! Сейчас у вас {count} слов.")
        main_menu(message.chat.id)
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка: {e}")
        main_menu(message.chat.id)


def delete_word(message):
    telegram_id = message.from_user.id
    cursor.execute("SELECT user_id FROM users WHERE telegram_id=%s", (telegram_id,))
    user_id = cursor.fetchone()[0]

    cursor.execute("""SELECT w.word_ru, w.word_en, uw.user_word_id 
                      FROM words w 
                      JOIN user_words uw ON w.word_id = uw.word_id 
                      WHERE uw.user_id=%s""", (user_id,))
    words = cursor.fetchall()
    if not words:
        bot.send_message(message.chat.id, "У вас нет слов для удаления.")
        main_menu(message.chat.id)
        return

    markup = types.InlineKeyboardMarkup()
    for w in words:
        markup.add(types.InlineKeyboardButton(f"{w[0]} - {w[1]}", callback_data=f"del_{w[2]}"))

    bot.send_message(message.chat.id, "Выберите слово для удаления:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('del_'))
def callback_delete(call):
    user_word_id = int(call.data.split('_')[1])
    cursor.execute("DELETE FROM user_words WHERE user_word_id=%s", (user_word_id,))
    conn.commit()
    bot.answer_callback_query(call.id, "Слово удалено!")
    bot.edit_message_text("Слово удалено.", call.message.chat.id, call.message.message_id)
    main_menu(call.message.chat.id)


def quiz(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)

    cursor.execute("SELECT word_id, word_ru, word_en FROM words ORDER BY RANDOM() LIMIT 1")
    word = cursor.fetchone()
    word_id, ru, correct_en = word

    cursor.execute("SELECT word_en FROM words WHERE word_id != %s ORDER BY RANDOM() LIMIT 3", (word_id,))
    options = [row[0] for row in cursor.fetchall()]
    options.append(correct_en)
    random.shuffle(options)

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)

    buttons = [types.KeyboardButton(opt) for opt in options]
    markup.add(*buttons)

    markup.add(types.KeyboardButton("Дальше ➡️"), types.KeyboardButton("Добавить слово ➕"))

    markup.add(types.KeyboardButton("Удалить слово 🔙"))

    msg = bot.send_message(message.chat.id, f"🇷🇺 Выбери перевод слова:\n{ru}", reply_markup=markup)
    bot.register_next_step_handler(msg, check_answer, ru, correct_en)


def check_answer(message, ru, correct_en):
    if message.text == correct_en:
        bot.send_message(message.chat.id, f"Молодец! ❤️\n{ru} -> {correct_en}\n\nИдём дальше 👉")
        quiz(message)
    elif message.text == "Дальше ➡️":
        quiz(message)
    elif message.text == "Добавить слово ➕":
        msg = bot.send_message(message.chat.id,
                               "Введите слово на русском и английском через запятую (например: море,sea)")
        bot.register_next_step_handler(msg, process_add)
    elif message.text == "Удалить слово 🔙":
        delete_word(message)
    else:
        bot.send_message(message.chat.id, "❌ Неправильно, попробуй ещё раз!")
        msg = bot.send_message(message.chat.id, "Выбери правильный вариант ещё раз:")
        bot.register_next_step_handler(msg, check_answer, ru, correct_en)


if __name__ == '__main__':
    print('Start telegram bot...')
    bot.polling()