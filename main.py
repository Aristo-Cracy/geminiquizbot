import os
import logging
import asyncio
from telegram import Bot
from telegram.ext import CommandHandler, MessageHandler, Filters, ApplicationBuilder, CallbackContext
from telegram.constants import ParseMode
from bs4 import BeautifulSoup

# --- Configuration ---
# You MUST replace these with your actual values
BOT_TOKEN = "7972418774:AAFgeS8Nw15K3tbY7akJ7im6cQHXZbeO3Ko"  # Get this from BotFather on Telegram
GROUP_CHAT_ID = "-4671966297"  # Get this by forwarding a message to @RawDataBot
ALLOWED_USER_ID = int("5218536687")  #  Replace with your Telegram user ID (as an integer)

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Helper Functions ---

def parse_mcq_from_html(html_content):
    """
    Parses the HTML content to extract MCQ questions, options, and image URLs.

    Args:
        html_content (str): The HTML content to parse.

    Returns:
        list: A list of dictionaries, where each dictionary represents a question
              and its data.  Example:
              [
                {
                    'question': 'What is the capital of France?',
                    'options': ['London', 'Paris', 'Berlin', 'Rome'],
                    'image_url': 'https://example.com/paris.jpg'  # Optional
                },
                ...
              ]
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        questions = []

        # Find all question containers.  Adjust the selector if your HTML is different.
        question_boxes = soup.find_all('div', class_='question-box')
        for question_box in question_boxes:
            question_text_element = question_box.find('p')  # Find the question text
            if not question_text_element:
                logging.warning("Question text not found. Skipping.")
                continue
            question_text = question_text_element.text.strip()

            # Find the options
            options = []
            answer_divs = question_box.find_next_siblings('div', class_='answer')  # Find answer divs
            for answer_div in answer_divs:
                option_text = answer_div.find('p').text.strip()
                options.append(option_text)

            # Extract image URL, if present.  Look in img tag *within* the question box.
            image_url = None
            img_tag = question_box.find('img')
            if img_tag:
                image_url = img_tag['src']

            if not options:
                logging.warning(f"No options found for question: {question_text}. Skipping.")
                continue
            questions.append({
                'question': question_text,
                'options': options,
                'image_url': image_url,
            })
        return questions
    
    except Exception as e:
        logging.error(f"Error parsing HTML: {e}")
        return []

async def send_poll_to_telegram(bot: Bot, chat_id, question_data):
    """
    Sends a poll to the specified Telegram group, handling images if present.

    Args:
        bot (telegram.Bot): The Telegram bot instance.
        chat_id (str): The ID of the chat to send the poll to.
        question_data (dict): A dictionary containing the question, options, and
                               optional image URL.
    """
    question_text = question_data['question']
    options = question_data['options']
    image_url = question_data.get('image_url')  # Use .get() to handle missing key

    try:
        if image_url:
            # Send the image first
            await bot.send_photo(chat_id=chat_id, photo=image_url)

        # Send the poll
        await bot.send_poll(
            chat_id=chat_id,
            question=question_text,
            options=options,
            is_anonymous=False,  # Set to False if you want to see who voted
        )
        logging.info(f"Poll sent successfully for question: {question_text[:20]}...") # Log first 20 chars
    except Exception as e:
        logging.error(f"Error sending poll: {e}")
        await bot.send_message(chat_id=chat_id, text=f"Failed to send poll: {e}")

# --- Command Handlers ---

async def start(update, context):
    """Sends a welcome message and instructions to the user."""
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Sorry, you are not authorized to use this bot."
        )
        return
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Hello {user.first_name}!\n\n"
             "I am a bot that can send MCQ questions as polls to a Telegram group.\n\n"
             "To use me, send me an HTML file containing your MCQ questions.\n\n"
             "Please ensure the HTML file is formatted correctly, with questions in "
             "<h3> tags and options in <li> tags within a <ul>.  Images should be in <img> tags.\n"
             "Example:\n"
             "<h3>What is the capital of France?</h3>\n"
             "<img src=\"https://example.com/paris.jpg\">\n"  # Example image URL
             "<ul><li>London</li><li>Paris</li><li>Berlin</li><li>Rome</li></ul>",
            parse_mode=ParseMode.HTML,  # Enable HTML parsing for the example
    )

async def handle_document(update, context):
    """
    Handles the document upload, parses the HTML, and sends polls.
    """
    user = update.effective_user
    if user.id != ALLOWED_USER_ID:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Sorry, you are not authorized to use this bot."
        )
        return

    chat_id = update.effective_chat.id
    document = update.message.document
    file_name = document.file_name

    if not file_name.endswith('.html'):
        await context.bot.send_message(chat_id=chat_id, text="Please upload an HTML file.")
        return

    try:
        # Get the file content
        file_content = await document.get_content()
        html_content = file_content.decode()  # Decode the bytes to a string

        # Parse the HTML
        questions = parse_mcq_from_html(html_content)
        if not questions:
            await context.bot.send_message(chat_id=chat_id, text="No valid MCQ questions found in the HTML file.")
            return

        # Confirmation message
        confirmation_text = f"Found {len(questions)} questions in {file_name}.\n\nDo you want to send them as polls to the group?"
        await context.bot.send_message(chat_id=chat_id, text=confirmation_text)

        # Use a one-time keyboard to get confirmation.
        reply_markup = telegram.ReplyKeyboardMarkup([['Yes', 'No']], one_time_keyboard=True)
        await context.bot.send_message(chat_id=chat_id, text="Please confirm:", reply_markup=reply_markup)

        # Store the questions in user_data for use in the confirmation handler
        context.user_data['questions'] = questions
        context.user_data['file_name'] = file_name #store file name

    except Exception as e:
        logging.error(f"Error processing document: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"Error processing the file: {e}")

async def handle_confirmation(update, context):
    """Handles the user's confirmation to send the polls."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text

    if user_id != ALLOWED_USER_ID:
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you are not authorized to use this bot.")
        return

    if text.lower() == 'yes':
        questions = context.user_data.get('questions') #get stored questions
        file_name = context.user_data.get('file_name')
        if not questions:
            await context.bot.send_message(chat_id=chat_id, text="No questions to send. Please upload an HTML file first.")
            return

        await context.bot.send_message(chat_id=chat_id, text=f"Sending {len(questions)} questions from {file_name} as polls...") #send file name
        # Send the polls
        for question_data in questions:
            await send_poll_to_telegram(context.bot, GROUP_CHAT_ID, question_data)
        await context.bot.send_message(chat_id=chat_id, text="All polls sent.")
        context.user_data.clear() # Clear user data
    elif text.lower() == 'no':
        await context.bot.send_message(chat_id=chat_id, text="Okay, I will not send the polls.")
        context.user_data.clear() # Clear user data
    else:
        await context.bot.send_message(chat_id=chat_id, text="Invalid option. Please reply with 'Yes' or 'No'.")

def main():
    """Main function to start the bot."""
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(Filters.document, handle_document))
    app.add_handler(MessageHandler(Filters.text, handle_confirmation)) #handle yes/no

    # Polling
    app.run_polling()

if __name__ == "__main__":
    main()
      
