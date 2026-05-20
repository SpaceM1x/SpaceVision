# SpaceVision

Минималистичное веб-приложение для загрузки космоснимков и подготовки к анализу дорог нейросетью.

## Стек

- Frontend: React + Vite + Leaflet
- Backend: FastAPI + SQLAlchemy
- Хранилище на старте: SQLite (временное решение до PostgreSQL)

## Быстрый запуск

### Одной командой

```bash
npm install
npm start
```

Команда запустит:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

### Если запускаете впервые

Установите Python-зависимости backend один раз:

```bash
python -m pip install -r backend/requirements.txt
```

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

## Обучение сегментации дорог

В проект добавлена базовая структура для обучения модели сегментации дорог на космоснимках:

```text
road_segmentation/
  data/         # сюда ляжет датасет
  checkpoints/  # веса модели
  outputs/      # результаты инференса
  train.py
  predict.py
  requirements.txt
```

### 1) Установите зависимости

```bash
python -m pip install -r road_segmentation/requirements.txt
```

### 2) Подготовьте датасет

Скопируйте данные в папку:

```text
road_segmentation/data
```

### 3) Запустите обучение

```bash
python road_segmentation/train.py --data-dir road_segmentation/data --checkpoints-dir road_segmentation/checkpoints --epochs 20
```

### 4) Запустите инференс

```bash
python road_segmentation/predict.py --image path/to/image.png --checkpoint road_segmentation/checkpoints/model.pth --output-dir road_segmentation/outputs
```
