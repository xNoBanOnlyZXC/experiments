from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

TOKEN = '-'

bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

class AnonState(StatesGroup):
    waiting_for_anon_message = State()

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message, state: FSMContext):
    command = message.get_command(pure=True)
    args = message.get_args()
    global user_id
    user_id = message.from_user.id + 11111

    if command == 'start' and args:
        global recipient_id
        recipient_id = int(args) - 11111
        await AnonState.waiting_for_anon_message.set()
        await bot.send_message(message.chat.id, "🚀 Здесь можно отправить анонимное сообщение человеку, который опубликовал эту ссылку.\n\nНапишите сюда всё, что хотите ему передать, и через несколько секунд он получит ваше сообщение, но не будет знать от кого.\n\nОтправить можно фото, видео, 💬 текст, 🔊 голосовые, 📷видеосообщения (кружки), а также стикеры.\n\n⚠️ Это полностью анонимно!", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add(types.KeyboardButton('Отменить отправку')))
    else:
        await bot.send_message(message.chat.id, f"🚀 Начни получать анонимные сообщения прямо сейчас!\n\nТвоя личная ссылка:\n👉 t.me/nboanonaskbot?start={user_id}\n\nРазмести эту ссылку ☝️ в своём профиле Telegram/Instagram/TikTok или других соц сетях, чтобы начать получать сообщения 💬")

@dp.message_handler(state=AnonState.waiting_for_anon_message)
async def process_anon_message(message: types.Message, state: FSMContext):
    global recipient_id
    global user_id
    reply_markup = types.InlineKeyboardMarkup()
    reply_button = types.InlineKeyboardButton("Ответить", url=f"t.me/nboanonaskbot?start={user_id}")
    reply_markup.add(reply_button)
    await bot.send_message(recipient_id, f"У тебя новое анонимное сообщение!\n\n{message.text}", reply_markup=reply_markup)
    await message.answer('Сообщение отправлено, ожидайте ответ!')
    await state.finish()

@dp.message_handler(lambda message: message.text and message.text.lower() == 'отменить отправку', state='*')
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer('Отправка отменена.', reply_markup=types.ReplyKeyboardRemove())

if __name__ == '__main__':
    executor.start_polling(dp)
