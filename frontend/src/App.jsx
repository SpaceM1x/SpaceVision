import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer } from "react-leaflet";
import { API_URL, getUploads, login, uploadTile } from "./api";

const tabs = [
  { key: "dashboard", label: "Обзор" },
  { key: "uploads", label: "Загрузки" },
  { key: "map", label: "Карта" },
  { key: "analytics", label: "Аналитика" },
  { key: "profile", label: "Профиль" },
];

function formatDate(value) {
  return new Date(value).toLocaleString("ru-RU");
}

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [uploads, setUploads] = useState([]);
  const [token, setToken] = useState(localStorage.getItem("token") || "");
  const [role, setRole] = useState(localStorage.getItem("role") || "viewer");
  const [username, setUsername] = useState(localStorage.getItem("username") || "");
  const [status, setStatus] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [tileForm, setTileForm] = useState({
    title: "",
    z: "",
    x: "",
    y: "",
  });
  const [credentials, setCredentials] = useState({
    username: "",
    password: "",
  });
  const [file, setFile] = useState(null);

  const canUpload = Boolean(token);
  const isAdmin = role === "admin";

  const withAdminTab = useMemo(() => {
    if (isAdmin) {
      return [...tabs, { key: "admin", label: "Админ-панель" }];
    }
    return tabs;
  }, [isAdmin]);

  async function loadUploads() {
    if (!token) {
      setUploads([]);
      return;
    }
    try {
      const data = await getUploads(token);
      setUploads(data);
    } catch (error) {
      setStatus(`Не удалось получить загрузки: ${error.message}`);
    }
  }

  useEffect(() => {
    loadUploads();
  }, [token]);

  async function handleLogin(event) {
    event.preventDefault();
    try {
      const result = await login(credentials.username, credentials.password);
      localStorage.setItem("token", result.access_token);
      localStorage.setItem("role", result.role);
      localStorage.setItem("username", result.username);
      setToken(result.access_token);
      setRole(result.role);
      setUsername(result.username);
      setStatus(`Вход выполнен: ${result.username}`);
      setCredentials({ username: "", password: "" });
    } catch (error) {
      setStatus(`Ошибка входа: ${error.message}`);
    }
  }

  function handleLogout() {
    localStorage.removeItem("token");
    localStorage.removeItem("role");
    localStorage.removeItem("username");
    setToken("");
    setRole("viewer");
    setUsername("");
    setUploads([]);
    setStatus("Вы вышли из системы.");
  }

  async function handleUpload(event) {
    event.preventDefault();
    if (!file) {
      setStatus("Выберите PNG/JPG файл тайла.");
      return;
    }
    setIsLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("title", tileForm.title);
      formData.append("tile_z", tileForm.z);
      formData.append("tile_x", tileForm.x);
      formData.append("tile_y", tileForm.y);
      await uploadTile(formData, token);
      setStatus("Снимок загружен.");
      setFile(null);
      setTileForm({ title: "", z: "", x: "", y: "" });
      await loadUploads();
      setActiveTab("uploads");
    } catch (error) {
      setStatus(`Ошибка загрузки: ${error.message}`);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>SpaceVision</h1>
          <p>Хранилище космоснимков с подготовкой к анализу дорог нейросетью.</p>
        </div>
        <div className="auth">
          {token ? (
            <>
              <span>{username || "Пользователь"} ({role})</span>
              <button onClick={handleLogout}>Выйти</button>
            </>
          ) : (
            <form onSubmit={handleLogin} className="login-form">
              <input
                placeholder="Логин"
                value={credentials.username}
                onChange={(event) =>
                  setCredentials((prev) => ({ ...prev, username: event.target.value }))
                }
              />
              <input
                placeholder="Пароль"
                type="password"
                value={credentials.password}
                onChange={(event) =>
                  setCredentials((prev) => ({ ...prev, password: event.target.value }))
                }
              />
              <button type="submit">Войти</button>
            </form>
          )}
        </div>
      </header>

      <nav className="tabs">
        {withAdminTab.map((tab) => (
          <button
            key={tab.key}
            className={activeTab === tab.key ? "tab active" : "tab"}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {status && <div className="status">{status}</div>}

      <main className="content">
        {activeTab === "dashboard" && (
          <section className="grid">
            <article className="card">
              <h2>Что уже готово</h2>
              <ul>
                <li>Загрузка тайлов и метаданных (z/x/y)</li>
                <li>История всех загрузок</li>
                <li>Роли: пользователь и админ</li>
                <li>Карта Leaflet с слоем ваших тайлов</li>
              </ul>
            </article>
            <article className="card">
              <h2>Следующий этап</h2>
              <p>
                После подключения нейросети сюда добавится детекция дорог и
                визуализация контуров на карте.
              </p>
            </article>
          </section>
        )}

        {activeTab === "uploads" && (
          <section className="grid">
            <article className="card">
              <h2>Новая загрузка</h2>
              <form onSubmit={handleUpload} className="upload-form">
                <input
                  placeholder="Название снимка"
                  value={tileForm.title}
                  onChange={(event) =>
                    setTileForm((prev) => ({ ...prev, title: event.target.value }))
                  }
                  disabled={!canUpload}
                />
                <div className="inputs-row">
                  <input
                    placeholder="z"
                    value={tileForm.z}
                    onChange={(event) =>
                      setTileForm((prev) => ({ ...prev, z: event.target.value }))
                    }
                    disabled={!canUpload}
                  />
                  <input
                    placeholder="x"
                    value={tileForm.x}
                    onChange={(event) =>
                      setTileForm((prev) => ({ ...prev, x: event.target.value }))
                    }
                    disabled={!canUpload}
                  />
                  <input
                    placeholder="y"
                    value={tileForm.y}
                    onChange={(event) =>
                      setTileForm((prev) => ({ ...prev, y: event.target.value }))
                    }
                    disabled={!canUpload}
                  />
                </div>
                <input
                  type="file"
                  accept=".png,.jpg,.jpeg"
                  onChange={(event) => setFile(event.target.files?.[0] || null)}
                  disabled={!canUpload}
                />
                <button type="submit" disabled={!canUpload || isLoading}>
                  {isLoading ? "Загрузка..." : "Загрузить"}
                </button>
              </form>
              {!canUpload && <p>Для загрузки войдите в аккаунт.</p>}
            </article>
            <article className="card">
              <h2>История загрузок</h2>
              <div className="history">
                {uploads.length === 0 ? (
                  <p>Пока нет загрузок.</p>
                ) : (
                  uploads.map((upload) => (
                    <div className="history-item" key={upload.id}>
                      <strong>{upload.title}</strong>
                      <span>{formatDate(upload.created_at)}</span>
                      <span>
                        tile: z{upload.tile_z} / x{upload.tile_x} / y{upload.tile_y}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </article>
          </section>
        )}

        {activeTab === "map" && (
          <section className="card map-card">
            <h2>Карта и тайлы Бурятии</h2>
            <p>Слой `Uploaded Tiles` читает ваши тайлы через API по z/x/y.</p>
            <MapContainer center={[52.1, 107.5]} zoom={8} className="map">
              <TileLayer
                attribution='&copy; OpenStreetMap contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <TileLayer
                attribution="Uploaded Tiles"
                url={`${API_URL}/tiles/{z}/{x}/{y}`}
                opacity={0.75}
              />
            </MapContainer>
          </section>
        )}

        {activeTab === "analytics" && (
          <section className="card">
            <h2>Аналитика (заготовка)</h2>
            <p>
              Здесь появятся результаты нейросети: маски дорог, площадь покрытия и
              экспорт GeoJSON.
            </p>
          </section>
        )}

        {activeTab === "profile" && (
          <section className="card">
            <h2>Личный кабинет</h2>
            <p>Имя: {username || "Гость"}</p>
            <p>Роль: {role}</p>
            <p>Загружено снимков: {uploads.length}</p>
          </section>
        )}

        {activeTab === "admin" && isAdmin && (
          <section className="card">
            <h2>Админ-панель</h2>
            <p>Загружено тайлов в системе: {uploads.length}</p>
            <p>
              Для следующих этапов: управление пользователями, аудит действий,
              ручная валидация датасета.
            </p>
          </section>
        )}
      </main>
    </div>
  );
}
