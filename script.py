import asyncio
import re
from collections import defaultdict, OrderedDict

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties

TOKEN = "8429624210:AAHFNaJ3mbrgvbWr5tq7jC_SoNAy1Zpudbo"
SOURCE_CHAT_ID = -4869365153    # <<< чат, где пользователи пишут
TARGET_CHAT_ID = -1002428030855 # <<< чат, куда бот публикует

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ---- Хранилище ----
schedule = defaultdict(lambda: {
    "msg_id": None,
    "panel_msg_id": None,
    "quests": OrderedDict()
})

# ---- Регулярки ----
DATE_RE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_RE_DOT = re.compile(r"^\d{2}[.\-/]\d{2}([.\-/]\d{4})?$")
TIME_RE = re.compile(r"^\d{1,2}[:.]\d{2}$")


def normalize_date_to_ddmm(s: str) -> str:
    s = s.strip()
    if DATE_RE_ISO.match(s):
        y, m, d = s.split("-")
        return f"{d}.{m}"
    if DATE_RE_DOT.match(s):
        parts = re.split(r"[.\-/]", s)
        d, m = parts[0], parts[1]
        return f"{d.zfill(2)}.{m.zfill(2)}"
    raise ValueError("Неверный формат даты")


def normalize_time_to_hhmm_dot(s: str) -> str:
    s = s.strip().replace(" ", "")
    s = s.replace(":", ".")
    if not TIME_RE.match(s.replace(".", ":")):
        if s.isdigit():
            h = int(s)
            return f"{h:02d}.00"
        raise ValueError("Неверный формат времени")
    h, m = s.split(".")
    return f"{int(h):02d}.{int(m):02d}"


def detect_actor_limit(quest: str) -> int:
    q = quest.lower()
    if "dead by daylight" in q:
        return 3
    if "amne" in q or "амнез" in q:
        return 2
    return 2


def sort_time_key(t: str) -> int:
    hh, mm = t.split(".")
    return int(hh) * 60 + int(mm)


# ---- Формирование текста ----
def format_schedule_text(date_ddmm: str) -> str:
    data = schedule[date_ddmm]
    lines = [f"{date_ddmm}", ""]
    for quest, times in data["quests"].items():
        lines.append(f"{quest}")
        for tm in sorted(times.keys(), key=sort_time_key):
            roles = times[tm]
            parts = []
            if roles["admin"]:
                parts.append(f"Администратор: {roles['admin']['name']}")
            if roles["actors"]:
                actor_names = [a["name"] for a in roles["actors"]]
                parts.append(f"Актеры: {', '.join(actor_names)}")
            inside = "; ".join(parts)
            lines.append(f"{tm} ({inside})" if inside else f"{tm} ()")
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


# ---- Клавиатуры ----
def quest_keyboard(date_ddmm: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=quest, callback_data=f"q|{date_ddmm}|{quest}")]
            for quest in schedule[date_ddmm]["quests"].keys()]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def time_keyboard(date_ddmm: str, quest: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=tm, callback_data=f"t|{date_ddmm}|{quest}|{tm}")]
            for tm in sorted(schedule[date_ddmm]["quests"].get(quest, {}).keys(), key=sort_time_key)]
    rows.append([InlineKeyboardButton(text="⬅️ К квестам", callback_data=f"backq|{date_ddmm}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def role_keyboard(date_ddmm: str, quest: str, tm: str) -> InlineKeyboardMarkup:
    slot = schedule[date_ddmm]["quests"][quest][tm]
    admin_taken = slot["admin"] is not None
    actor_limit = detect_actor_limit(quest)
    actors_count = len(slot["actors"])

    rows = []
    if not admin_taken:
        rows.append([InlineKeyboardButton(text="Администратор", callback_data=f"r|{date_ddmm}|{quest}|{tm}|admin")])
    else:
        rows.append([InlineKeyboardButton(text="Администратор (занято)", callback_data=f"r|{date_ddmm}|{quest}|{tm}|admin")])

    rows.append([InlineKeyboardButton(
        text=f"Актер ({actors_count}/{actor_limit})",
        callback_data=f"r|{date_ddmm}|{quest}|{tm}|actor"
    )])
    rows.append([InlineKeyboardButton(text="⬅️ К времени", callback_data=f"backt|{date_ddmm}|{quest}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---- Приём сообщений ----
@dp.message(F.chat.id == SOURCE_CHAT_ID, F.text)
async def on_source_message(msg: Message):
    lines = [ln.strip() for ln in msg.text.split("\n") if ln.strip()]
    if len(lines) < 3:
        return

    first, second, third = lines[0], lines[1], lines[2]
    try:
        if DATE_RE_ISO.match(first) or DATE_RE_DOT.match(first):
            date_ddmm = normalize_date_to_ddmm(first)
            quest = second
            tm = normalize_time_to_hhmm_dot(third)
        else:
            quest = first
            date_ddmm = normalize_date_to_ddmm(second)
            tm = normalize_time_to_hhmm_dot(third)
    except Exception:
        return

    if quest not in schedule[date_ddmm]["quests"]:
        schedule[date_ddmm]["quests"][quest] = OrderedDict()
    if tm not in schedule[date_ddmm]["quests"][quest]:
        schedule[date_ddmm]["quests"][quest][tm] = {"admin": None, "actors": []}

    text = format_schedule_text(date_ddmm)

    if not schedule[date_ddmm]["msg_id"]:
        sent = await bot.send_message(TARGET_CHAT_ID, text)
        schedule[date_ddmm]["msg_id"] = sent.message_id
        panel = await bot.send_message(
            TARGET_CHAT_ID,
            f"Выберите квест для {date_ddmm}:",
            reply_markup=quest_keyboard(date_ddmm)
        )
        schedule[date_ddmm]["panel_msg_id"] = panel.message_id
    else:
        await bot.edit_message_text(
            chat_id=TARGET_CHAT_ID,
            message_id=schedule[date_ddmm]["msg_id"],
            text=text
        )
        if schedule[date_ddmm]["panel_msg_id"]:
            await bot.edit_message_text(
                chat_id=TARGET_CHAT_ID,
                message_id=schedule[date_ddmm]["panel_msg_id"],
                text=f"Выберите квест для {date_ddmm}:",
                reply_markup=quest_keyboard(date_ddmm)
            )


# ---- Обработка инлайн-кнопок ----
@dp.callback_query(F.data.startswith(("q|", "t|", "r|", "backq|", "backt|", "noop")))
async def on_cb(cb: CallbackQuery):
    try:
        parts = cb.data.split("|")
        kind = parts[0]

        if kind == "noop":
            await cb.answer()
            return

        if kind == "q":
            _, date_ddmm, quest = parts
            await cb.message.edit_text(
                f"Вы выбрали квест: <b>{quest}</b>\nВыберите время:",
                reply_markup=time_keyboard(date_ddmm, quest)
            )
            await cb.answer()

        elif kind == "backq":
            _, date_ddmm = parts
            await cb.message.edit_text(
                f"Выберите квест для {date_ddmm}:",
                reply_markup=quest_keyboard(date_ddmm)
            )
            await cb.answer()

        elif kind == "t":
            _, date_ddmm, quest, tm = parts
            await cb.message.edit_text(
                f"<b>{quest}</b> — {tm}\nВыберите роль:",
                reply_markup=role_keyboard(date_ddmm, quest, tm)
            )
            await cb.answer()

        elif kind == "backt":
            _, date_ddmm, quest = parts
            await cb.message.edit_text(
                f"Вы выбрали квест: <b>{quest}</b>\nВыберите время:",
                reply_markup=time_keyboard(date_ddmm, quest)
            )
            await cb.answer()

        elif kind == "r":
            _, date_ddmm, quest, tm, role = parts
            slot = schedule[date_ddmm]["quests"][quest][tm]
            user_id = cb.from_user.id
            user_name = cb.from_user.full_name

            if role == "admin":
                if slot["admin"] is None:
                    slot["admin"] = {"id": user_id, "name": user_name}
                    await cb.answer("Вы записаны администратором ✅")
                elif slot["admin"]["id"] == user_id:
                    slot["admin"] = None
                    await cb.answer("Вы снялись с роли администратора ❌")
                else:
                    await cb.answer("Администратор уже занят", show_alert=True)
                    return

            elif role == "actor":
                limit = detect_actor_limit(quest)
                existing_ids = [a["id"] for a in slot["actors"]]

                if user_id in existing_ids:
                    slot["actors"] = [a for a in slot["actors"] if a["id"] != user_id]
                    await cb.answer("Вы снялись с актеров ❌")
                else:
                    if len(slot["actors"]) >= limit:
                        await cb.answer("Все места актеров заняты", show_alert=True)
                        return
                    slot["actors"].append({"id": user_id, "name": user_name})
                    await cb.answer("Вы записаны как актер ✅")

            new_text = format_schedule_text(date_ddmm)
            await bot.edit_message_text(
                chat_id=TARGET_CHAT_ID,
                message_id=schedule[date_ddmm]["msg_id"],
                text=new_text
            )
            await cb.message.edit_text(
                f"<b>{quest}</b> — {tm}\nВыберите роль:",
                reply_markup=role_keyboard(date_ddmm, quest, tm)
            )

    except Exception as e:
        print("Callback error:", e)
        try:
            await cb.answer("Ошибка обработки", show_alert=True)
        except:
            pass


# ---- Запуск ----
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
