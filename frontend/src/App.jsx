import { useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  History,
  LayoutDashboard,
  Map,
  Upload,
  UserCog,
  UserRound,
} from "lucide-react";
import { MapContainer, TileLayer } from "react-leaflet";
import { API_URL, getUploads, login, uploadTile } from "./api";

const menuItems = [
  { key: "maps", label: "Карты", icon: Map },
  { key: "upload", label: "Загрузка космоснимков", icon: Upload },
  { key: "statistics", label: "Статистика", icon: BarChart3 },
  { key: "history", label: "История загрузок космоснимков", icon: History },
  { key: "profile", label: "Личный кабинет", icon: UserRound },
];

function formatDate(value) {
  return new Date(value).toLocaleString("ru-RU");
}

export default function App() {
  const [activeTab, setActiveTab] = useState("maps");
  const [baseLayer, setBaseLayer] = useState("scheme");
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
  const [searchQuery, setSearchQuery] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const canUpload = Boolean(token);
  const isAdmin = role === "admin";

  const fullMenu = useMemo(() => {
    if (isAdmin) {
      return [
        ...menuItems,
        { key: "admin", label: "Администрирование", icon: UserCog },
      ];
    }
    return menuItems;
  }, [isAdmin]);

  const filteredUploads = useMemo(() => {
    return uploads.filter((upload) => {
      const normalizedTitle = upload.title.toLowerCase();
      const matchesTitle = normalizedTitle.includes(searchQuery.toLowerCase().trim());
      const uploadDate = new Date(upload.created_at);

      const fromBoundary = dateFrom ? new Date(`${dateFrom}T00:00:00`) : null;
      const toBoundary = dateTo ? new Date(`${dateTo}T23:59:59`) : null;

      const matchesFrom = fromBoundary ? uploadDate >= fromBoundary : true;
      const matchesTo = toBoundary ? uploadDate <= toBoundary : true;

      return matchesTitle && matchesFrom && matchesTo;
    });
  }, [uploads, searchQuery, dateFrom, dateTo]);

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
      setStatus("");
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
    setStatus("");
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
      const uploaded = await uploadTile(formData, token);
      setStatus(
        uploaded?.mask_url
          ? "Снимок загружен. Дороги распознаны, маска готова."
          : "Снимок загружен."
      );
      setFile(null);
      setTileForm({ title: "", z: "", x: "", y: "" });
      await loadUploads();
      setActiveTab("history");
    } catch (error) {
      setStatus(`Ошибка загрузки: ${error.message}`);
    } finally {
      setIsLoading(false);
    }
  }

  if (!token) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <h1>SpaceVision</h1>
          <p className="auth-subtitle">
            Войдите в систему для работы с космоснимками и картой.
          </p>
          <form onSubmit={handleLogin} className="auth-form">
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
          {status && <div className="status">{status}</div>}
        </div>
      </div>
    );
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <LayoutDashboard size={18} />
          <div>
            <strong>SpaceVision</strong>
            <span>Диспетчер космоснимков</span>
          </div>
        </div>
        <nav className="menu">
          {fullMenu.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                className={activeTab === item.key ? "menu-item active" : "menu-item"}
                onClick={() => setActiveTab(item.key)}
              >
                <span className="menu-left">
                  <Icon size={17} />
                  <span className="menu-label">{item.label}</span>
                </span>
              </button>
            );
          })}
        </nav>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div>
            <h1>SpaceVision</h1>
            <p>Платформа для работы с космоснимками и картографическими слоями.</p>
          </div>
          <div className="auth">
            <span className="user-badge">
              {username || "Пользователь"} ({role})
            </span>
            <button onClick={handleLogout}>Выйти</button>
          </div>
        </header>

        {status && <div className="status">{status}</div>}

        <main className="content">
          {activeTab === "upload" && (
          <section className="grid">
            <article className="card">
              <h2>Загрузка космоснимков</h2>
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
                    placeholder="z (опционально)"
                    value={tileForm.z}
                    onChange={(event) =>
                      setTileForm((prev) => ({ ...prev, z: event.target.value }))
                    }
                    disabled={!canUpload}
                  />
                  <input
                    placeholder="x (опционально)"
                    value={tileForm.x}
                    onChange={(event) =>
                      setTileForm((prev) => ({ ...prev, x: event.target.value }))
                    }
                    disabled={!canUpload}
                  />
                  <input
                    placeholder="y (опционально)"
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
          </section>
          )}

          {activeTab === "statistics" && (
          <section className="grid">
            <article className="card">
              <h2>Статистика</h2>
              <ul>
                <li>Всего загружено снимков: {uploads.length}</li>
                <li>Активная роль: {role}</li>
                <li>Текущий пользователь: {username}</li>
              </ul>
            </article>
            <article className="card">
              <h2>Аналитический модуль</h2>
              <p>Этот раздел является заготовкой на будущее.</p>
            </article>
          </section>
          )}

          {activeTab === "maps" && (
            <section className="card map-card">
              <div className="map-toolbar">
                <div>
                  <h2>Карты</h2>
                  <p>Доступны режимы отображения: схема и спутниковая подложка.</p>
                </div>
                <div className="layer-switcher">
                  <button
                    className={baseLayer === "scheme" ? "layer-btn active" : "layer-btn"}
                    onClick={() => setBaseLayer("scheme")}
                  >
                    Схема
                  </button>
                  <button
                    className={
                      baseLayer === "satellite" ? "layer-btn active" : "layer-btn"
                    }
                    onClick={() => setBaseLayer("satellite")}
                  >
                    Спутник
                  </button>
                </div>
              </div>
              <MapContainer center={[52.1, 107.5]} zoom={8} className="map">
                {baseLayer === "scheme" ? (
                  <TileLayer
                    attribution='&copy; OpenStreetMap contributors'
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                  />
                ) : (
                  <TileLayer
                    attribution="Tiles &copy; Esri"
                    url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                  />
                )}
                <TileLayer
                  attribution="Uploaded Tiles"
                  url={`${API_URL}/tiles/{z}/{x}/{y}`}
                  opacity={0.75}
                />
              </MapContainer>
            </section>
          )}

          {activeTab === "history" && (
            <section className="card">
              <h2>История загрузок космоснимков</h2>
              <div className="history-filters">
                <input
                  type="text"
                  placeholder="Поиск по названию снимка"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                />
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(event) => setDateFrom(event.target.value)}
                />
                <input
                  type="date"
                  value={dateTo}
                  onChange={(event) => setDateTo(event.target.value)}
                />
              </div>
              <div className="history">
                {filteredUploads.length === 0 ? (
                  <p>По выбранным фильтрам ничего не найдено.</p>
                ) : (
                  filteredUploads.map((upload) => (
                    <div className="history-item" key={upload.id}>
                      <strong>{upload.title}</strong>
                      <span>{formatDate(upload.created_at)}</span>
                      <span>
                        tile: z{upload.tile_z} / x{upload.tile_x} / y{upload.tile_y}
                      </span>
                      {(upload.mask_url || upload.overlay_url) && (
                        <span>
                          {upload.mask_url && (
                            <a
                              href={`${API_URL}${upload.mask_url}`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Маска дорог
                            </a>
                          )}
                          {upload.mask_url && upload.overlay_url && " · "}
                          {upload.overlay_url && (
                            <a
                              href={`${API_URL}${upload.overlay_url}`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Оверлей
                            </a>
                          )}
                        </span>
                      )}
                    </div>
                  ))
                )}
              </div>
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
            <p>Этот раздел является заготовкой на будущее.</p>
          </section>
          )}
        </main>
      </div>
    </div>
  );
}
