# SpaceVision — оценка риска лесных пожаров

Веб-приложение для оценки вероятности лесных пожаров на территории Заиграевского
района (Республика Бурятия). Работает в двух режимах:

- **ИИ режим** — распознавание дорог на космоснимках нейросетью (U-Net).
- **Shape режим** — расчёт риска пожара по дорожной сети из ESRI Shapefile.

## Возможности

### Общее
- Авторизация по логину/паролю (`admin / admin123`, `operator / operator123`).
- Сворачиваемое боковое меню (кнопка-гамбургер): два режима + «Личный кабинет».
- SQLite-база, состояние сохраняется между запусками.

### ИИ режим
- Карта космоснимков (подложка OSM / спутник).
- Загрузка космоснимков (PNG/JPG) с автосегментацией дорог.
- Кнопка-прицел: установка точки и заглушка ответа ИИ (риск по историческим документам).
- Загрузка документов (заглушка модуля).
- Статистика: доля дорог, тренд, топ снимков.
- История загрузок с маской/оверлеем.

### Shape режим
- Карта риска: клик по карте считает вероятность пожара в точке.
- Загрузка SHP (.shp/.shx/.dbf/.prj) и очистка загруженных файлов.
- Панель справа от карты — подробный разбор каждого фактора расчёта.
- История расчётов: каждая строка раскрывается в полное объяснение.

## Формула расчёта риска

```
road_proximity       = exp(-d_road_osm / 1000)
settlement_proximity = exp(-d_settlement / 3000)

P_base = clamp(0.05
        + 0.18·road_proximity
        + 0.20·settlement_proximity
        + 0.12·road_density
        + 0.08·settlement_density
        + 0.15·season
        + 0.10·diurnal
        + 0.15·road_proximity·settlement_proximity, 0, 0.90)

I(R)   = 1 / (1 + R / R0)          # R — расстояние до SHP-дороги, R0 = 500 м
P_fire = P_base + alpha·I(R)·(1 − P_base)   # alpha = 0.30
```

- `d_road_osm`, `d_settlement`, `road_density`, `settlement_density` — контекст OSM (Overpass).
- `season` — сезонный фактор `[0,1]` (июль — максимум, январь — минимум).
- `diurnal` — суточный фактор `[0,1]` (пик в 15:00 местного времени).

## Структура

```
backend/            FastAPI (auth, roads, risk, uploads, analytics)
  app/
  tests/            pytest
frontend/           React + Leaflet
  src/App.jsx       UI
  src/api.js        HTTP-клиент
  src/styles.css
gis/roads/          загруженные Shapefile (в Git не хранятся)
road_segmentation/  чекпоинт модели U-Net
```

## Запуск

Требования: Python 3.10+, Node.js 18+.

```bash
# бэкенд
pip install -r backend/requirements.txt
python -m uvicorn app.main:app --reload --port 8000 --app-dir backend

# фронтенд
cd frontend && npm install && npm run dev
```

Или всё сразу из корня: `npm start`.

Фронтенд: http://localhost:5173, API: http://localhost:8000 (документация — `/docs`).

## Тесты

```bash
cd backend && python -m pytest
```

## Переменные окружения

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `ROADS_SHP_PATH` | путь к Shapefile дорог | `gis/roads/roads.shp` |
| `R0_METERS` | характерное расстояние влияния дороги | `500` |
| `ALPHA` | вес влияния SHP-дороги | `0.30` |
| `METRIC_CRS` | метрическая CRS (иначе UTM по центроиду) | пусто |

## Технологии

FastAPI, SQLAlchemy (SQLite), PyJWT, GeoPandas/Shapely/PyProj, React, Leaflet,
react-leaflet, PyTorch + segmentation-models-pytorch (сегментация дорог).
