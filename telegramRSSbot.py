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

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)


# SQLITE


def sqlite_connect():
    global conn
    conn = sqlite3.connect('config/rss.db', check_same_thread=False)


def sqlite_load_all():
    c = conn.cursor()
    c.execute('SELECT * FROM rss')
    rows = c.fetchall()
    feeds = {}
    for row in rows:
        feeds[row[0]] = (row[1], rows[2])
    return feeds


def sqlite_load_all_banned_words():
    c = conn.cursor()
    c.execute('SELECT * FROM banned_word')
    rows = c.fetchall()
    result = []
    for row in rows:
        result.append(row[0])
    return result


def sqlite_write(name, link, last):
    c = conn.cursor()
    q = [name, link, last]
    c.execute('''INSERT INTO rss('name','link','last') VALUES(?,?,?)''', q)
    conn.commit()


def sqlite_write_ban(word: str):
    c = conn.cursor()
    q = [(word.lower())]
    c.execute('''INSERT INTO banned_word('value') VALUES(?)''', q)
    conn.commit()


def cmd_rss_list(update, context):
    feeds = sqlite_load_all()
    if len(feeds) == 0:
        update.effective_message.reply_text("Database empty")
        return
    for name, url_list in feeds.items():
        update.effective_message.reply_text(
            "Title: " + name +
            "\nrss url: " + str(url_list[0]) +
            "\nlast checked article: " + str(url_list[1]))


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
    except IndexError:
        update.effective_message.reply_text(
            "ERROR: The link does not seem to be a RSS feed or is not supported")
        raise
    sqlite_write(context.args[0], context.args[1],
                 str(rss_d.entries[0]['link']))
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
    update.effective_message.reply_text("added \nBanned word: %s" % (context.args[0]))


def cmd_rss_list_ban(update, context):
    rows = sqlite_load_all_banned_words()
    if len(rows) == 0:
        update.effective_message.reply_text("Database empty")
        return
    for title in rows:
        update.effective_message.reply_text("Word: " + title)


def cmd_rss_delete_ban(update, context):
    c = conn.cursor()
    q = (context.args[0],)
    m = ""
    try:
        c.execute("DELETE FROM banned_word WHERE value = ?", q)
        conn.commit()
    except sqlite3.Error as e:
        print('Error %s:' % e.args[0])
        m = e.args[0]
    update.effective_message.reply_text("Removed: " + context.args[0] + "\n" + m)


def cmd_rss_remove(update, context):
    c = conn.cursor()
    q = (context.args[0],)
    m = ""
    try:
        c.execute("DELETE FROM rss WHERE name = ?", q)
        conn.commit()
    except sqlite3.Error as e:
        print('Error %s:' % e.args[0])
        m = e.args[0]
    update.effective_message.reply_text("Removed: " + context.args[0] + "\n" + m)


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


def check_entry_contains_banned_word(banned_words, entry_detail):
    for word in banned_words:
        if word in entry_detail:
            return True
    return False


def check_entry_budget(detail):
    budget = re.search("Budget.*?: \\$([0-9,]+)", detail).group(1).replace(",", "")
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
    c = conn.cursor()
    q = [(link)]
    c.execute('SELECT * FROM messages_send WHERE link = ?', q)
    rows = c.fetchall()
    return len(rows) > 0


def save_message_send(link):
    c = conn.cursor()
    q = [(str(link))]
    c.execute('''INSERT INTO messages_send('link') VALUES(?)''', q)
    conn.commit()


def send_message_to_chat(banned_words, name, context, rss_entry):
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

    if check_entry_contains_banned_word(banned_words, str(detail).lower()):
        return

    save_message_send(rss_entry['link'])
    context.bot.send_message(chatid, prefix + rss_entry['link'].replace('?source=rss', "") + " " + name + " " + budget)


def rss_monitor(context):
    feeds = sqlite_load_all()
    banned_words = sqlite_load_all_banned_words()
    for name, url_list in feeds.items():
        rss_d = feedparser.parse(url_list[0])
        if "entries" not in rss_d or len(rss_d.entries) == 0:
            print(f"{name} url returns empty entries")
            continue
        for i in range(min(15, len(rss_d.entries))):
            entry = rss_d.entries[i]
            if url_list[1] != entry['link']:
                q = [name, url_list[0], str(entry['link'])]
                c = conn.cursor()
                c.execute('''INSERT INTO rss('name','link','last') VALUES(?,?,?)''', q)
                conn.commit()
                send_message_to_chat(banned_words, name, context, entry)


def cmd_test(update, context):
    url = "https://www.reddit.com/r/funny/new/.rss"
    rss_d = feedparser.parse(url)
    update.effective_message.reply_text(rss_d.entries[0]['link'])


def init_sqlite():
    sqlite_connect()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS rss (name text, link text, last text)''')
    c.execute('''CREATE TABLE IF NOT EXISTS banned_word (value text)''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages_send (link text)''')
    conn.commit()

import html
import json


def error_handler(update: Update, context: CallbackContext) -> None:
    # traceback.format_exception returns the usual python message about an exception, but as a
    # list of strings rather than a single string, so we have to join them together.
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = ''.join(tb_list)

    # Build the message with some markup and additional information about what happened.
    # You might need to add some logic to deal with messages longer than the 4096 character limit.
    update_mess = ""
    if update:
        update_mess = html.escape(json.dumps(update.to_dict(), indent=2, ensure_ascii=False))
    message = (
        f'An exception was raised while handling an update\n'
        f'<pre>update = {update_mess}'
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

    job_queue.run_repeating(rss_monitor, delay)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
