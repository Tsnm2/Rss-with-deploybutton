import feedparser
import logging
import sqlite3
import os
import re
from telegram.ext import Updater, CallbackContext, CommandHandler
from telegram import Update, ParseMode
from pathlib import Path
import traceback

Path("config").mkdir(parents=True, exist_ok=True)

# Docker env
if os.environ.get('TOKEN'):
    Token = os.environ['TOKEN']
    chatid = os.environ['CHATID']
    delay = int(os.environ['DELAY'])
else:
    Token = "X"
    chatid = "X"
    delay = 60

if Token == "X":
    print("Token not set!")

rss_dict = {}
banned_word_list = []

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)


# SQLITE


def sqlite_connect():
    global conn
    conn = sqlite3.connect('config/rss.db', check_same_thread=False)


def sqlite_load_all():
    sqlite_connect()
    c = conn.cursor()
    c.execute('SELECT * FROM rss')
    rows = c.fetchall()
    conn.close()
    return rows


def sqlite_load_all_banned_words():
    sqlite_connect()
    c = conn.cursor()
    c.execute('SELECT * FROM banned_word')
    rows = c.fetchall()
    conn.close()
    return rows


def sqlite_write(name, link, last):
    sqlite_connect()
    c = conn.cursor()
    q = [(name), (link), (last)]
    c.execute('''INSERT INTO rss('name','link','last') VALUES(?,?,?)''', q)
    conn.commit()
    conn.close()


def sqlite_write_ban(word: str):
    sqlite_connect()
    c = conn.cursor()
    q = [(word.lower())]
    c.execute('''INSERT INTO banned_word('value') VALUES(?)''', q)
    conn.commit()
    conn.close()


# RSS________________________________________
def rss_load():
    # if the dict is not empty, empty it.
    if bool(rss_dict):
        rss_dict.clear()

    for row in sqlite_load_all():
        rss_dict[row[0]] = (row[1], row[2])


def banned_word_load():
    # if the dict is not empty, empty it.
    if bool(banned_word_list):
        banned_word_list.clear()

    for row in sqlite_load_all_banned_words():
        banned_word_list.append(row[0])


def cmd_rss_list(update, context):
    if bool(rss_dict) is False:

        update.effective_message.reply_text("The database is empty")
    else:
        for title, url_list in rss_dict.items():
            update.effective_message.reply_text(
                "Title: " + title +
                "\nrss url: " + url_list[0] +
                "\nlast checked article: " + url_list[1])


def cmd_rss_add(update, context):
    # try if there are 2 arguments passed
    try:
        context.args[1]
    except IndexError:
        update.effective_message.reply_text(
            "ERROR: The format needs to be: /add title http://www.URL.com")
        raise
    # try if the url is a valid RSS feed
    try:
        rss_d = feedparser.parse(context.args[1])
        rss_d.entries[0]['title']
    except IndexError:
        update.effective_message.reply_text(
            "ERROR: The link does not seem to be a RSS feed or is not supported")
        raise
    sqlite_write(context.args[0], context.args[1],
                 str(rss_d.entries[0]['link']))
    rss_load()
    update.effective_message.reply_text(
        "added \nTITLE: %s\nRSS: %s" % (context.args[0], context.args[1]))


def cmd_rss_add_ban(update, context):
    # try if there are 2 arguments passed
    try:
        context.args[0]
    except IndexError:
        update.effective_message.reply_text("ERROR: The format needs to be: /ban word")
        raise
    sqlite_write_ban(context.args[0])
    banned_word_load()
    update.effective_message.reply_text("added \nBanned word: %s" % (context.args[0]))


def cmd_rss_list_ban(update, context):
    if len(banned_word_list) == 0:
        update.effective_message.reply_text("The database is empty")
    else:
        for title in banned_word_list:
            update.effective_message.reply_text("Word: " + title)


def cmd_rss_delete_ban(update, context):
    conn = sqlite3.connect('config/rss.db')
    c = conn.cursor()
    q = (context.args[0],)
    try:
        c.execute("DELETE FROM banned_word WHERE value = ?", q)
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print('Error %s:' % e.args[0])
    banned_word_load()
    update.effective_message.reply_text("Removed: " + context.args[0])


def cmd_rss_remove(update, context):
    conn = sqlite3.connect('config/rss.db')
    c = conn.cursor()
    q = (context.args[0],)
    try:
        c.execute("DELETE FROM rss WHERE name = ?", q)
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print('Error %s:' % e.args[0])
    rss_load()
    update.effective_message.reply_text("Removed: " + context.args[0])


def cmd_help(update, context):
    print(context.chat_data)
    update.effective_message.reply_text(
        "RSS to Telegram bot" +
        "\n\nAfter successfully adding a RSS link, the bot starts fetching the feed every "
        + str(delay) + " seconds. (This can be set)" +
        "\n\nTitles are used to easily manage RSS feeds and need to contain only one word" +
        "\n\ncommands:" +
        "\n/help Posts this help message" +
        "\n/add title http://www(.)RSS-URL(.)com" +
        "\n/remove !Title! removes the RSS link" +
        "\n/list Lists all the titles and the RSS links from the DB" +
        "\n/add_ban word" +
        "\n/list_ban Lists all the banned words" +
        "\n/delete_ban word Delete word from the banned words" +
        "\n/test Inbuilt command that fetches a post from Reddits RSS." +
        "\n\nThe current chatId is: " + str(update.message.chat.id))


def check_entry_contains_banned_word(entry_detail):
    for ban in banned_word_list:
        if ban in entry_detail:
            return False
    return True


def check_entry_budget(detail):
    budget = re.search("Budget.*?: \\$([0-9]+)", detail).group(1)
    if int(budget) > 99:
        return True, budget
    return False, ''


def get_hourly_price(detail):
    price = re.search("Hourly Range.*?: (.*)\n", detail).group(1)
    prices = price.replace('$', '').split('-')
    if len(prices) == 1:
        return float(prices[0]) >= 25, price
    if len(prices) == 2:
        low, high = float(prices[0]), float(prices[1])
        return (low >= 25 or high >= 25), price
    return True, price


def check_blocked_country(detail):
    country = re.search("Country.*?: (.*)\n", detail).group(1).lower()
    if country in "india":
        return False
    return True


def is_message_already_send(link):
    sqlite_connect()
    c = conn.cursor()
    q = [(link)]
    c.execute('SELECT * FROM messages_send WHERE link = ?', q)
    rows = c.fetchall()
    conn.close()
    return len(rows) > 0


def save_message_send(link):
    sqlite_connect()
    c = conn.cursor()
    q = [(str(link))]
    c.execute('''INSERT INTO messages_send('link') VALUES(?)''', q)
    conn.commit()
    conn.close()


def send_message_to_chat(name, context, rss_entry):
    detail = rss_entry["summary_detail"]["value"]

    send_message = True

    budget = ''
    if "Budget" in detail:
        send_message, budget = check_entry_budget(detail)
    elif "Hourly Range" in detail:
        send_message, budget = get_hourly_price(detail)

    prefix = ""
    if send_message and "Country" in detail and not check_blocked_country(detail):
        prefix = "⚠️⚠️⚠️⚠️"

    if not send_message:
        return

    if is_message_already_send(rss_entry['link']):
        return

    if not check_entry_contains_banned_word(str(detail).lower()):
        return

    save_message_send(rss_entry['link'])
    context.bot.send_message(chatid, prefix + rss_entry['link'].replace('?source=rss', "") + " " + name + " " + budget)


def rss_monitor(context):
    for name, url_list in rss_dict.items():
        rss_d = feedparser.parse(url_list[0])
        if "entries" not in rss_d or len(rss_d.entries) == 0:
            print(f"{name} url returns empty entries")
            continue
        for i in range(min(15, len(rss_d.entries))):
            entry = rss_d.entries[i]
            if url_list[1] != entry['link']:
                conn = sqlite3.connect('config/rss.db')
                q = [(name), (url_list[0]), (str(entry['link']))]
                c = conn.cursor()
                c.execute('''INSERT INTO rss('name','link','last') VALUES(?,?,?)''', q)
                conn.commit()
                conn.close()
                rss_load()
                send_message_to_chat(name, context, entry)


def cmd_test(update, context):
    url = "https://www.reddit.com/r/funny/new/.rss"
    rss_d = feedparser.parse(url)
    rss_d.entries[0]['link']
    update.effective_message.reply_text(rss_d.entries[0]['link'])


def init_sqlite():
    conn = sqlite3.connect('config/rss.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS rss (name text, link text, last text)''')
    c.execute('''CREATE TABLE IF NOT EXISTS banned_word (value text)''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages_send (link text)''')

import html
import json


def error_handler(update: Update, context: CallbackContext) -> None:
    # traceback.format_exception returns the usual python message about an exception, but as a
    # list of strings rather than a single string, so we have to join them together.
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = ''.join(tb_list)

    # Build the message with some markup and additional information about what happened.
    # You might need to add some logic to deal with messages longer than the 4096 character limit.
    message = (
        f'An exception was raised while handling an update\n'
        f'<pre>update = {html.escape(json.dumps(update.to_dict(), indent=2, ensure_ascii=False))}'
        '</pre>\n\n'
        f'<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n'
        f'<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n'
        f'<pre>{html.escape(tb_string)}</pre>'
    )

    # Finally, send the message
    context.bot.send_message(chat_id=chatid, text=message, parse_mode=ParseMode.HTML)



def main():
    updater = Updater(token=Token, use_context=True)
    job_queue = updater.job_queue
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("add", cmd_rss_add))
    dp.add_handler(CommandHandler("help", cmd_help))
    dp.add_handler(CommandHandler("test", cmd_test, ))
    dp.add_handler(CommandHandler("list", cmd_rss_list))
    dp.add_handler(CommandHandler("remove", cmd_rss_remove))
    dp.add_handler(CommandHandler("add_ban", cmd_rss_add_ban))
    dp.add_handler(CommandHandler("list_ban", cmd_rss_list_ban))
    dp.add_handler(CommandHandler("delete_ban", cmd_rss_delete_ban))

    dp.add_error_handler(error_handler)

    # try to create a database if missing
    try:
        init_sqlite()
    except sqlite3.OperationalError:
        pass
    rss_load()

    job_queue.run_repeating(rss_monitor, delay)

    updater.start_polling()
    updater.idle()
    conn.close()


if __name__ == '__main__':
    main()
