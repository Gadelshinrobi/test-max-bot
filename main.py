from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import httpx
import os
import json
from dotenv import load_dotenv
from database import get_db, Article, Subscriber
from pydantic import BaseModel
import asyncio

load_dotenv()

app = FastAPI()

class MaxWebhook(BaseModel):
    event: str
    user_id: str
    text: str
    chat_id: str

# Функция отправки сообщения в MAX
async def send_to_max(chat_id: str, text: str, keyboard=None):
    async with httpx.AsyncClient() as client:
        try:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "bot_id": os.getenv("MAX_BOT_ID")
            }
            
            # Если есть клавиатура, добавляем её
            if keyboard:
                payload["keyboard"] = keyboard
            
            response = await client.post(
                f"{os.getenv('MAX_API_URL')}/messages",
                headers={"Authorization": f"Bearer {os.getenv('MAX_BOT_TOKEN')}"},
                json=payload
            )
            if response.status_code != 200:
                print(f"Ошибка отправки: {response.text}")
            return response
        except Exception as e:
            print(f"Ошибка подключения: {e}")
            return None

# Функция для создания клавиатуры (меню)
def create_main_menu():
    return {
        "buttons": [
            [
                {"text": "📰 Новости", "command": "news"},
                {"text": "📂 Категории", "command": "categories"}
            ],
            [
                {"text": "🔍 Поиск", "command": "search"},
                {"text": "ℹ️ Помощь", "command": "help"}
            ]
        ]
    }

def create_news_menu():
    return {
        "buttons": [
            [
                {"text": "📋 Все новости", "command": "all_news"},
                {"text": "📌 Последние", "command": "latest_news"}
            ],
            [
                {"text": "🔙 Назад", "command": "menu"}
            ]
        ]
    }

@app.post("/webhook/max")
async def max_webhook(data: MaxWebhook, db: Session = Depends(get_db)):
    if data.event != "message_new":
        return {"status": "ok"}
    
    user_id = data.user_id
    text = data.text.strip().lower()
    chat_id = data.chat_id
    
    # Регистрация пользователя
    subscriber = db.query(Subscriber).filter_by(max_user_id=user_id).first()
    if not subscriber:
        new_user = Subscriber(max_user_id=user_id, full_name=f"Пользователь_{user_id[:8]}")
        db.add(new_user)
        db.commit()
        await send_to_max(chat_id, "👋 Добро пожаловать! Я информационный бот.", create_main_menu())
        return {"status": "ok"}
    
    # === ГЛАВНОЕ МЕНЮ ===
    if text == "/start" or text == "/menu":
        await send_to_max(chat_id, "🏠 Главное меню:\n\nВыберите действие:", create_main_menu())
    
    # === НОВОСТИ ===
    elif text == "/news" or text == "📰 новости":
        articles = db.query(Article).filter_by(is_published=True).order_by(Article.created_at.desc()).limit(5).all()
        if articles:
            msg = "📰 Последние 5 новостей:\n\n"
            for i, art in enumerate(articles, 1):
                msg += f"{i}. *{art.title}*\n{art.content[:100]}...\n\n"
            await send_to_max(chat_id, msg, create_news_menu())
        else:
            await send_to_max(chat_id, "📭 Нет опубликованных новостей.", create_news_menu())
    
    # === ВСЕ НОВОСТИ ===
    elif text == "/all_news" or text == "📋 все новости":
        articles = db.query(Article).filter_by(is_published=True).order_by(Article.created_at.desc()).all()
        if articles:
            msg = "📋 Все новости:\n\n"
            for art in articles[:10]:  # Показываем 10, чтобы не было слишком длинно
                msg += f"• {art.title} ({art.category})\n"
            msg += f"\nВсего статей: {len(articles)}"
            await send_to_max(chat_id, msg, create_news_menu())
        else:
            await send_to_max(chat_id, "📭 Нет опубликованных новостей.", create_news_menu())
    
    # === ПОСЛЕДНИЕ НОВОСТИ ===
    elif text == "/latest_news" or text == "📌 последние":
        articles = db.query(Article).filter_by(is_published=True).order_by(Article.created_at.desc()).limit(3).all()
        if articles:
            for art in articles:
                msg = f"📌 *{art.title}*\n"
                msg += f"📂 {art.category}\n"
                msg += f"📅 {art.created_at.strftime('%d.%m.%Y')}\n\n"
                msg += f"{art.content}"
                await send_to_max(chat_id, msg)
            await send_to_max(chat_id, "✅ Все последние новости показаны.", create_news_menu())
        else:
            await send_to_max(chat_id, "📭 Нет новостей.", create_news_menu())
    
    # === КАТЕГОРИИ ===
    elif text == "/categories" or text == "📂 категории":
        categories = db.query(Article.category).distinct().all()
        if categories:
            msg = "📂 Доступные категории:\n\n"
            for cat in categories:
                count = db.query(Article).filter_by(category=cat[0]).count()
                msg += f"• {cat[0]} ({count} статей)\n"
            
            # Создаем кнопки с категориями
            category_buttons = []
            row = []
            for i, cat in enumerate(categories):
                row.append({"text": cat[0], "command": f"category_{cat[0]}"})
                if len(row) == 2:
                    category_buttons.append(row)
                    row = []
            if row:
                category_buttons.append(row)
            category_buttons.append([{"text": "🔙 Назад", "command": "menu"}])
            
            keyboard = {"buttons": category_buttons}
            await send_to_max(chat_id, msg, keyboard)
        else:
            await send_to_max(chat_id, "📭 Нет категорий.", create_main_menu())
    
    # === ПОИСК ПО КАТЕГОРИИ ===
    elif text.startswith("/category_"):
        category = text.replace("/category_", "")
        articles = db.query(Article).filter_by(category=category, is_published=True).all()
        if articles:
            msg = f"📂 Категория: {category}\n\n"
            for art in articles[:5]:
                msg += f"• {art.title}\n"
            if len(articles) > 5:
                msg += f"\n... и ещё {len(articles) - 5} статей"
            await send_to_max(chat_id, msg, create_main_menu())
        else:
            await send_to_max(chat_id, f"📭 В категории '{category}' нет статей.", create_main_menu())
    
    # === ПОИСК ===
    elif text == "/search" or text == "🔍 поиск":
        await send_to_max(chat_id, "🔍 Введите поисковый запрос:\n\nПример: /search новости")
    
    elif text.startswith("/search "):
        keyword = text.replace("/search ", "").strip()
        if not keyword:
            await send_to_max(chat_id, "❌ Введите что-то для поиска.\nПример: /search новости")
            return {"status": "ok"}
        
        results = db.query(Article).filter(
            Article.title.contains(keyword) | Article.content.contains(keyword)
        ).limit(5).all()
        
        if results:
            msg = f"🔍 Результаты поиска по запросу '{keyword}':\n\n"
            for art in results:
                msg += f"• {art.title} ({art.category})\n"
            await send_to_max(chat_id, msg, create_main_menu())
        else:
            await send_to_max(chat_id, f"❌ По запросу '{keyword}' ничего не найдено.", create_main_menu())
    
    # === ПОМОЩЬ ===
    elif text == "/help" or text == "ℹ️ помощь":
        await send_to_max(chat_id, 
            "📚 *Справка по боту*\n\n"
            "Доступные команды:\n"
            "• /menu - Показать главное меню\n"
            "• /news - Последние новости\n"
            "• /categories - Список категорий\n"
            "• /search текст - Поиск по статьям\n"
            "• /help - Эта справка\n\n"
            "Также можно использовать кнопки меню!",
            create_main_menu()
        )
    
    # === НЕИЗВЕСТНАЯ КОМАНДА ===
    else:
        await send_to_max(chat_id, 
            "❌ Неизвестная команда.\n"
            "Напишите /help для списка команд или /menu для меню.",
            create_main_menu()
        )
    
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "Бот работает", "status": "active"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}