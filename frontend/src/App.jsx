import { useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  History,
  LayoutDashboard,
  Map as MapIcon,
  Upload,
  UserCog,
  UserRound,
} from "lucide-react";
import {
  CircleMarker,
  ImageOverlay,
  MapContainer,
  Marker,
  Popup,
  Rectangle,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { API_URL, getAnalyticsSummary, getPointRisk, getUploads, login, uploadTile } from "./api";

const menuItems = [
  { key: "maps", label: "Карты", icon: MapIcon },
  { key: "upload", label: "Загрузка космоснимков", icon: Upload },
  { key: "statistics", label: "Статистика", icon: BarChart3 },
  { key: "history", label: "История загрузок космоснимков", icon: History },
  { key: "profile", label: "Личный кабинет", icon: UserRound },
];

function formatDate(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString("ru-RU");
}

function MapClickHandler({ onClick }) {
  useMapEvents({
    click(event) {
      onClick(event.latlng);
    },
  });
  return null;
}

function MapViewportController({ focusBounds }) {
  const map = useMap();

  useEffect(() => {
    if (!focusBounds) return;
    map.fitBounds(focusBounds, { padding: [30, 30] });
  }, [map, focusBounds]);

  return null;
}

function getUploadBounds(upload) {
  const minLat = Number(upload?.min_lat);
  const maxLat = Number(upload?.max_lat);
  const minLon = Number(upload?.min_lon);
  const maxLon = Number(upload?.max_lon);
  if (
    !Number.isFinite(minLat) ||
    !Number.isFinite(maxLat) ||
    !Number.isFinite(minLon) ||
    !Number.isFinite(maxLon)
  ) {
    return null;
  }
  if (
    minLat < -90 ||
    maxLat > 90 ||
    minLon < -180 ||
    maxLon > 180 ||
    Math.abs(maxLat - minLat) > 40 ||
    Math.abs(maxLon - minLon) > 40
  ) {
    return null;
  }
  return [
    [Math.min(minLat, maxLat), Math.min(minLon, maxLon)],
    [Math.max(minLat, maxLat), Math.max(minLon, maxLon)],
  ];
}

function PieChart({ value, size = 130, color = "#3a8d5f", background = "#e1efe4", label }) {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  const style = {
    width: `${size}px`,
    height: `${size}px`,
    background: `conic-gradient(${color} ${clamped}%, ${background} ${clamped}% 100%)`,
  };
  return (
    <div className="pie-wrapper">
      <div className="pie-chart" style={style}>
        <div className="pie-inner">
          <strong>{clamped.toFixed(1)}%</strong>
          {label && <span>{label}</span>}
        </div>
      </div>
    </div>
  );
}

function TrendChart({ points }) {
  if (!points || points.length === 0) {
    return <p className="chart-empty">Недостаточно данных для графика.</p>;
  }

  const maxY = Math.max(...points.map((item) => item.road_percentage), 1);
  const minY = Math.min(...points.map((item) => item.road_percentage), 0);
  const rangeY = Math.max(maxY - minY, 1e-6);
  const width = 680;
  const height = 240;
  const pad = 28;

  const mapped = points.map((point, index) => {
    const x = pad + (index * (width - pad * 2)) / Math.max(points.length - 1, 1);
    const y = height - pad - ((point.road_percentage - minY) / rangeY) * (height - pad * 2);
    return { ...point, x, y };
  });
  const polyline = mapped.map((item) => `${item.x},${item.y}`).join(" ");

  return (
    <div className="trend-chart-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} className="trend-chart" role="img">
        <rect x="0" y="0" width={width} height={height} className="trend-chart-bg" />
        <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} className="trend-axis" />
        <line x1={pad} y1={pad} x2={pad} y2={height - pad} className="trend-axis" />
        <polyline points={polyline} className="trend-line" />
        {mapped.map((item) => (
          <g key={item.id}>
            <circle cx={item.x} cy={item.y} r="4" className="trend-point" />
            <title>{`${item.title}: ${item.road_percentage.toFixed(2)}%`}</title>
          </g>
        ))}
      </svg>
    </div>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState("maps");
  const [baseLayer, setBaseLayer] = useState("scheme");
  const [uploads, setUploads] = useState([]);
  const [token, setToken] = useState(localStorage.getItem("token") || "");
  const [role, setRole] = useState(localStorage.getItem("role") || "viewer");
  const [username, setUsername] = useState(localStorage.getItem("username") || "");
  const [isLoading, setIsLoading] = useState(false);
  const [nnProgress, setNnProgress] = useState(0);
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
  const [analytics, setAnalytics] = useState(null);
  const [selectedPoint, setSelectedPoint] = useState(null);
  const [pointRisk, setPointRisk] = useState(null);
  const [isPointRiskLoading, setIsPointRiskLoading] = useState(false);
  const [pointRiskProgress, setPointRiskProgress] = useState(0);
  const [mapFocusBounds, setMapFocusBounds] = useState(null);
  const [detectedRoadCenter, setDetectedRoadCenter] = useState(null);
  const [activeMapOverlay, setActiveMapOverlay] = useState(null);

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

  const safeUploads = useMemo(() => (Array.isArray(uploads) ? uploads : []), [uploads]);

  const filteredUploads = useMemo(() => {
    return safeUploads.filter((upload) => {
      const normalizedTitle = String(upload?.title ?? "").toLowerCase();
      const matchesTitle = normalizedTitle.includes(searchQuery.toLowerCase().trim());
      const uploadDate = new Date(upload?.created_at ?? 0);

      const fromBoundary = dateFrom ? new Date(`${dateFrom}T00:00:00`) : null;
      const toBoundary = dateTo ? new Date(`${dateTo}T23:59:59`) : null;

      const matchesFrom = fromBoundary ? uploadDate >= fromBoundary : true;
      const matchesTo = toBoundary ? uploadDate <= toBoundary : true;

      return matchesTitle && matchesFrom && matchesTo;
    });
  }, [safeUploads, searchQuery, dateFrom, dateTo]);

  async function loadUploads() {
    if (!token) {
      setUploads([]);
      return;
    }
    try {
      const data = await getUploads(token);
      setUploads(data);
    } catch (error) {
      console.error("Не удалось получить загрузки:", error);
    }
  }

  async function loadAnalytics() {
    if (!token) {
      setAnalytics(null);
      return;
    }
    try {
      const summary = await getAnalyticsSummary(token);
      setAnalytics(summary);
    } catch (error) {
      console.error("Не удалось получить аналитику:", error);
    }
  }

  useEffect(() => {
    loadUploads();
    loadAnalytics();
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
      setCredentials({ username: "", password: "" });
    } catch (error) {
      console.error("Ошибка входа:", error);
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
    setAnalytics(null);
    setActiveMapOverlay(null);
  }

  async function handleUpload(event) {
    event.preventDefault();
    if (!file) {
      return;
    }
    setIsLoading(true);
    setNnProgress(0);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("title", tileForm.title);
      formData.append("tile_z", tileForm.z);
      formData.append("tile_x", tileForm.x);
      formData.append("tile_y", tileForm.y);
      const progressTimer = setInterval(() => {
        setNnProgress((prev) => Math.min(prev + 8, 94));
      }, 180);
      try {
        await Promise.all([uploadTile(formData, token), new Promise((resolve) => setTimeout(resolve, 2200))]);
      } finally {
        clearInterval(progressTimer);
      }
      setNnProgress(100);
      setFile(null);
      setTileForm({ title: "", z: "", x: "", y: "" });
      await loadUploads();
      await loadAnalytics();
      setActiveTab("history");
    } catch (error) {
      console.error("Ошибка загрузки:", error);
    } finally {
      setIsLoading(false);
      window.setTimeout(() => setNnProgress(0), 700);
    }
  }

  async function handleMapPointSelect(latlng) {
    if (!latlng || !token) return;
    setMapFocusBounds(null);
    setDetectedRoadCenter(null);
    setSelectedPoint(latlng);
    setIsPointRiskLoading(true);
    setPointRiskProgress(0);
    try {
      const progressTimer = setInterval(() => {
        setPointRiskProgress((prev) => Math.min(prev + 7, 93));
      }, 170);
      try {
        const [risk] = await Promise.all([
          getPointRisk(token, latlng.lat, latlng.lng),
          new Promise((resolve) => setTimeout(resolve, 1200)),
        ]);
        setPointRisk(risk);
      } finally {
        clearInterval(progressTimer);
      }
      setPointRiskProgress(100);
    } catch (error) {
      setPointRisk(null);
      console.error("Не удалось рассчитать риск пожара:", error);
    } finally {
      setIsPointRiskLoading(false);
      window.setTimeout(() => setPointRiskProgress(0), 700);
    }
  }

  function handleOpenUploadOnMap(upload) {
    const bounds = getUploadBounds(upload);
    if (!bounds) return;
    const centerLat = (bounds[0][0] + bounds[1][0]) / 2;
    const centerLon = (bounds[0][1] + bounds[1][1]) / 2;
    const overlayPath = upload?.overlay_url ? `${API_URL}${upload.overlay_url}` : null;
    setMapFocusBounds(bounds);
    setDetectedRoadCenter({ lat: centerLat, lng: centerLon });
    setActiveMapOverlay(
      overlayPath
        ? {
            id: upload.id,
            title: upload.title || "Без названия",
            bounds,
            url: overlayPath,
          }
        : null
    );
    setSelectedPoint(null);
    setPointRisk(null);
    setIsPointRiskLoading(false);
    setPointRiskProgress(0);
    setActiveTab("maps");

    if (token) {
      handleMapPointSelect({ lat: centerLat, lng: centerLon });
    }
  }

  const analyticsItems = Array.isArray(analytics?.items) ? analytics.items : [];
  const timelinePoints = Array.isArray(analytics?.timeline) ? analytics.timeline : [];
  const analyticsByUploadId = useMemo(
    () => new Map(analyticsItems.map((item) => [item.id, item])),
    [analyticsItems]
  );
  const topRoadItems = [...analyticsItems]
    .sort((a, b) => b.road_percentage - a.road_percentage)
    .slice(0, 5);
  const averageRoad = analytics?.average_road_percentage ?? 0;
  const globalCoverage = analytics?.global_road_coverage ?? 0;
  const maxRoad = analytics?.max_road_percentage ?? 0;
  const averageComponents = analytics?.average_component_count ?? 0;
  const uploadsByUser = useMemo(() => {
    const grouped = new Map();
    for (const upload of safeUploads) {
      const userKey = upload?.uploaded_by || "unknown";
      grouped.set(userKey, (grouped.get(userKey) || 0) + 1);
    }
    return Array.from(grouped.entries())
      .map(([user, count]) => ({ user, count }))
      .sort((a, b) => b.count - a.count || a.user.localeCompare(b.user));
  }, [safeUploads]);

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
                  accept=".png,.jpg,.jpeg,.tif,.tiff"
                  onChange={(event) => setFile(event.target.files?.[0] || null)}
                  disabled={!canUpload}
                />
                <button type="submit" disabled={!canUpload || isLoading}>
                  {isLoading ? "Загрузка..." : "Загрузить"}
                </button>
                {isLoading && (
                  <div className="progress-wrap">
                    <div className="progress-head">
                      <span>Нейросеть обрабатывает снимок...</span>
                      <strong>{nnProgress}%</strong>
                    </div>
                    <div className="progress-track">
                      <div className="progress-fill" style={{ width: `${nnProgress}%` }} />
                    </div>
                  </div>
                )}
              </form>
              {!canUpload && <p>Для загрузки войдите в аккаунт.</p>}
            </article>
          </section>
          )}

          {activeTab === "statistics" && (
          <section className="statistics-layout">
            <article className="card stats-kpis">
              <h2>Статистика</h2>
              <div className="kpi-grid">
                <div className="kpi-item">
                  <span>Всего снимков</span>
                  <strong>{analytics?.total_uploads ?? uploads.length}</strong>
                </div>
                <div className="kpi-item">
                  <span>С масками</span>
                  <strong>{analytics?.uploads_with_predictions ?? 0}</strong>
                </div>
                <div className="kpi-item">
                  <span>Средний % дорог</span>
                  <strong>{averageRoad.toFixed(2)}%</strong>
                </div>
                <div className="kpi-item">
                  <span>Макс % дорог</span>
                  <strong>{maxRoad.toFixed(2)}%</strong>
                </div>
                <div className="kpi-item">
                  <span>Среднее число фрагментов</span>
                  <strong>{averageComponents.toFixed(1)}</strong>
                </div>
                <div className="kpi-item">
                  <span>Текущий пользователь</span>
                  <strong>{username}</strong>
                </div>
              </div>
            </article>

            <div className="grid">
              <article className="card">
                <h2>Доля дорог (по всем пикселям)</h2>
                <PieChart value={globalCoverage} label="дороги" />
                <p className="chart-caption">
                  Глобальное покрытие дорог на всех обработанных снимках.
                </p>
              </article>
              <article className="card">
                <h2>Средний снимок</h2>
                <PieChart value={averageRoad} color="#2c9a66" label="дороги" />
                <p className="chart-caption">
                  Средняя доля дорожной поверхности на одном загруженном снимке.
                </p>
              </article>
            </div>

            <article className="card">
              <h2>Тренд распознанной дорожной площади</h2>
              <TrendChart points={timelinePoints} />
            </article>

            <article className="card">
              <h2>Топ снимков по доле дорог</h2>
              {topRoadItems.length === 0 ? (
                <p className="chart-empty">Пока нет данных для рейтинга.</p>
              ) : (
                <div className="top-list">
                  {topRoadItems.map((item, index) => (
                    <div className="top-item" key={item.id}>
                      <div>
                        <strong>
                          {index + 1}. {item.title}
                        </strong>
                        <span>{formatDate(item.created_at)}</span>
                      </div>
                      <div className="top-bar-wrap">
                        <div
                          className="top-bar"
                          style={{ width: `${Math.max(1, Math.min(100, item.road_percentage))}%` }}
                        />
                      </div>
                      <strong>{item.road_percentage.toFixed(2)}%</strong>
                    </div>
                  ))}
                </div>
              )}
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
              <div className="map-point-info">
                {!selectedPoint && !detectedRoadCenter && (
                  <p>Кликните по карте для расчета вероятности пожара.</p>
                )}
                {activeMapOverlay && (
                  <p>
                    Оверлей нейросети для снимка <strong>{activeMapOverlay.title}</strong> отображается на
                    участке TIFF.
                  </p>
                )}
                {(selectedPoint || detectedRoadCenter) && (
                  <>
                    {isPointRiskLoading && (
                      <div className="progress-wrap">
                        <div className="progress-head">
                          <span>Расчет вероятности пожара...</span>
                          <strong>{pointRiskProgress}%</strong>
                        </div>
                        <div className="progress-track">
                          <div
                            className="progress-fill"
                            style={{ width: `${pointRiskProgress}%` }}
                          />
                        </div>
                      </div>
                    )}
                    {!isPointRiskLoading && pointRisk && (
                      <div className="fire-risk-single">
                        <span>Вероятность пожара</span>
                        <strong>{pointRisk.fire_probability.toFixed(1)}%</strong>
                        {pointRisk.risk_reason && <p>{pointRisk.risk_reason}</p>}
                      </div>
                    )}
                  </>
                )}
              </div>
              <MapContainer center={[52.1, 107.5]} zoom={8} className="map">
                <MapClickHandler onClick={handleMapPointSelect} />
                <MapViewportController focusBounds={mapFocusBounds} />
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
                {activeMapOverlay && (
                  <ImageOverlay
                    bounds={activeMapOverlay.bounds}
                    url={activeMapOverlay.url}
                    opacity={0.66}
                  />
                )}
                {selectedPoint && (
                  <Marker position={[selectedPoint.lat, selectedPoint.lng]}>
                    <Popup>
                      Точка риска пожара
                      <br />
                      {selectedPoint.lat.toFixed(6)}, {selectedPoint.lng.toFixed(6)}
                    </Popup>
                  </Marker>
                )}
                {detectedRoadCenter && (
                  <CircleMarker
                    center={[detectedRoadCenter.lat, detectedRoadCenter.lng]}
                    radius={9}
                    pathOptions={{
                      color: "#d81b60",
                      weight: 3,
                      fillColor: "#ec407a",
                      fillOpacity: 0.45,
                    }}
                  >
                    <Popup>Найденный участок дороги (TIFF)</Popup>
                  </CircleMarker>
                )}
                {mapFocusBounds && (
                  <Rectangle
                    bounds={mapFocusBounds}
                    pathOptions={{ color: "#e53935", weight: 2, fillOpacity: 0.06 }}
                  />
                )}
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
                  filteredUploads.map((upload) => {
                    const analyticsEntry = analyticsByUploadId.get(upload.id);
                    const roadPercent = analyticsEntry?.road_percentage ?? 0;
                    const clampedRoadPercent = Math.max(0, Math.min(100, roadPercent));
                    return (
                      <div className="history-item" key={upload.id ?? String(upload.title)}>
                        <strong>{upload.title || "Без названия"}</strong>
                        <span>{formatDate(upload.created_at)}</span>
                        <span>
                          tile: z{upload.tile_z} / x{upload.tile_x} / y{upload.tile_y}
                        </span>
                        <div className="history-road-metric">
                          <div className="history-road-metric-head">
                            <span>% пикселей дорог</span>
                            <strong>{clampedRoadPercent.toFixed(2)}%</strong>
                          </div>
                          <div className="history-road-bar-wrap">
                            <div
                              className="history-road-bar"
                              style={{ width: `${Math.max(1, clampedRoadPercent)}%` }}
                            />
                          </div>
                        </div>
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
                        {getUploadBounds(upload) && (
                          <button type="button" onClick={() => handleOpenUploadOnMap(upload)}>
                            Перейти на карту с оверлеем
                          </button>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </section>
          )}

          {activeTab === "profile" && (
          <section className="card">
            <h2>Личный кабинет</h2>
            <div className="kpi-grid">
              <div className="kpi-item">
                <span>Имя</span>
                <strong>{username || "Гость"}</strong>
              </div>
              <div className="kpi-item">
                <span>Роль</span>
                <strong>{role}</strong>
              </div>
              <div className="kpi-item">
                <span>Загружено снимков</span>
                <strong>{analytics?.total_uploads ?? uploads.length}</strong>
              </div>
              <div className="kpi-item">
                <span>Снимков с масками</span>
                <strong>{analytics?.uploads_with_predictions ?? 0}</strong>
              </div>
            </div>
            <div className="grid" style={{ marginTop: "12px" }}>
              <article className="card">
                <h2>Последняя загрузка</h2>
                {uploads[0] ? (
                  <>
                    <p>
                      <strong>{uploads[0].title || "Без названия"}</strong>
                    </p>
                    <p>{formatDate(uploads[0].created_at)}</p>
                    {uploads[0].mask_url && (
                      <p>
                        <a href={`${API_URL}${uploads[0].mask_url}`} target="_blank" rel="noreferrer">
                          Открыть маску дорог
                        </a>
                      </p>
                    )}
                  </>
                ) : (
                  <p>Пока нет загрузок.</p>
                )}
              </article>
            </div>
          </section>
          )}

          {activeTab === "admin" && isAdmin && (
          <section className="statistics-layout">
            <article className="card">
              <h2>Админ-панель</h2>
              <div className="kpi-grid">
                <div className="kpi-item">
                  <span>Всего снимков</span>
                  <strong>{safeUploads.length}</strong>
                </div>
                <div className="kpi-item">
                  <span>Пользователей с загрузками</span>
                  <strong>{uploadsByUser.length}</strong>
                </div>
              </div>
            </article>

            <article className="card">
              <h2>Загрузки по пользователям</h2>
              {uploadsByUser.length === 0 ? (
                <p className="chart-empty">Пока нет данных.</p>
              ) : (
                <div className="top-list">
                  {uploadsByUser.map((entry) => (
                    <div className="top-item" key={entry.user}>
                      <div>
                        <strong>{entry.user}</strong>
                        <span>Пользователь системы</span>
                      </div>
                      <div className="top-bar-wrap">
                        <div
                          className="top-bar"
                          style={{
                            width: `${Math.max(
                              5,
                              (entry.count / Math.max(safeUploads.length, 1)) * 100
                            )}%`,
                          }}
                        />
                      </div>
                      <strong>{entry.count}</strong>
                    </div>
                  ))}
                </div>
              )}
            </article>

            <article className="card">
              <h2>Все загруженные снимки</h2>
              {safeUploads.length === 0 ? (
                <p className="chart-empty">Пока нет загруженных снимков.</p>
              ) : (
                <div className="history">
                  {safeUploads.map((upload) => (
                    <div className="history-item" key={`admin-upload-${upload.id}`}>
                      <strong>{upload.title || "Без названия"}</strong>
                      <span>Пользователь: {upload.uploaded_by || "unknown"}</span>
                      <span>{formatDate(upload.created_at)}</span>
                      <span>
                        tile: z{upload.tile_z} / x{upload.tile_x} / y{upload.tile_y}
                      </span>
                      <span>
                        {upload.image_url && (
                          <a href={`${API_URL}${upload.image_url}`} target="_blank" rel="noreferrer">
                            Оригинал
                          </a>
                        )}
                        {upload.image_url && upload.mask_url && " · "}
                        {upload.mask_url && (
                          <a href={`${API_URL}${upload.mask_url}`} target="_blank" rel="noreferrer">
                            Маска дорог
                          </a>
                        )}
                        {(upload.image_url || upload.mask_url) && upload.overlay_url && " · "}
                        {upload.overlay_url && (
                          <a href={`${API_URL}${upload.overlay_url}`} target="_blank" rel="noreferrer">
                            Оверлей
                          </a>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </article>
          </section>
          )}
        </main>
      </div>
    </div>
  );
}
