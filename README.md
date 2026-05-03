# SpaceVision

Минималистичное веб-приложение для загрузки космоснимков и подготовки к анализу дорог нейросетью.

## Стек

- Frontend: React + Vite + Leaflet
- Backend: FastAPI + SQLAlchemy
- Хранилище на старте: SQLite (временное решение до PostgreSQL)

## Быстрый запуск

### 1) Backend

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Backend: `http://127.0.0.1:8000`

### 2) Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend: `http://127.0.0.1:5173`

## Демо-аккаунты

- admin / admin123 (есть вкладка админ-панели)
- operator / operator123

## Что реализовано

- Логин и роли (пользователь/админ)
- Личный кабинет
- Загрузка космоснимков (PNG/JPG) с координатами тайла `z/x/y`
- История загрузок
- Карта Leaflet с наложением пользовательских тайлов через API `/tiles/{z}/{x}/{y}`
- Заготовка вкладки аналитики для следующего этапа (нейросеть)
