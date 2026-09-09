import { useEffect, useState } from "react";
import L from "leaflet";
import {
  LayoutDashboard,
  Map as MapIcon,
  Upload,
  UserRound,
} from "lucide-react";
import {
  GeoJSON,
  MapContainer,
  Marker,
  Popup,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import {
  getPointRisk,
  getRoads,
  getRoadsStatus,
  login,
  uploadRoads,
} from "./api";

const menuItems = [
  { key: "maps", label: "Карты", icon: MapIcon },
  { key: "upload", label: "Загрузка SHP", icon: Upload },
  { key: "profile", label: "Личный кабинет", icon: UserRound },
];

const DEFAULT_CENTER = [51.85, 108.27];
const DEFAULT_ZOOM = 9;

function riskEmoji(level) {
  if (level === "high") return "🔥";
  if (level === "medium") return "⚠️";
  return "🌲";
}

function riskLabel(level) {
  if (level === "high") return "Высокий";
  if (level === "medium") return "Средний";
  return "Низкий";
}

function MapClickHandler({ onClick }) {
  useMapEvents({ click: (event) => onClick(event.latlng) });
  return null;
}

function RoadsFitBounds({ data }) {
  const map = useMap();
  useEffect(() => {
    if (!data || !data.features || data.features.length === 0) return;
    const bounds = L.geoJSON(data).getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [30, 30] });
  }, [data, map]);
  return null;
}

function LoginScreen({ onSubmit }) {
  const [credentials, setCredentials] = useState({ username: "", password: "" });
  const [error, setError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    try {
      const result = await login(credentials.username, credentials.password);
      onSubmit(result);
    } catch (err) {
      setError(err.message || "Неверный логин или пароль.");
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>SpaceVision</h1>
        <p className="auth-subtitle">
          Заиграевский район: карта риска пожаров. Дороги загружаются из Shapefile (без нейросети).
        </p>
        <form onSubmit={handleSubmit} className="auth-form">
          <input
            placeholder="Логин"
            value={credentials.username}
            onChange={(event) => setCredentials((prev) => ({ ...prev, username: event.target.value }))}
            autoFocus
          />
          <input
            placeholder="Пароль"
            type="password"
            value={credentials.password}
            onChange={(event) => setCredentials((prev) => ({ ...prev, password: event.target.value }))}
          />
          {error && <p style={{ color: "#b91c1c", margin: 0 }}>{error}</p>}
          <button type="submit">Войти</button>
        </form>
        <p style={{ fontSize: 12, color: "var(--text-muted)" }}>admin / admin123 · operator / operator123</p>
      </div>
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState(localStorage.getItem("token") || "");
  const [username, setUsername] = useState(localStorage.getItem("username") || "");
  const [role, setRole] = useState(localStorage.getItem("role") || "viewer");
  const [activeTab, setActiveTab] = useState("maps");

  const [baseLayer, setBaseLayer] = useState("scheme");
  const [roads, setRoads] = useState(null);
  const [roadsError, setRoadsError] = useState("");
  const [roadsStatus, setRoadsStatus] = useState(null);
  const [selectedPoint, setSelectedPoint] = useState(null);
  const [pointRisk, setPointRisk] = useState(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const [riskError, setRiskError] = useState("");

  const [uploadFiles, setUploadFiles] = useState([]);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState("");
  const [uploadError, setUploadError] = useState("");

  function loadRoads() {
    if (!token) return;
    setRoadsError("");
    setRoads(null);
    getRoads(token)
      .then((data) => setRoads(data))
      .catch((err) => setRoadsError(err.message || "Не удалось загрузить дороги."));
    getRoadsStatus(token)
      .then((status) => setRoadsStatus(status))
      .catch(() => setRoadsStatus(null));
  }

  useEffect(() => {
    if (!token) return;
    loadRoads();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function handleLogin(result) {
    localStorage.setItem("token", result.access_token);
    localStorage.setItem("role", result.role);
    localStorage.setItem("username", result.username);
    setToken(result.access_token);
    setRole(result.role);
    setUsername(result.username);
    setActiveTab("maps");
  }

  function handleLogout() {
    localStorage.removeItem("token");
    localStorage.removeItem("role");
    localStorage.removeItem("username");
    setToken("");
    setRole("viewer");
    setUsername("");
    setActiveTab("maps");
    setRoads(null);
    setRoadsStatus(null);
    setSelectedPoint(null);
    setPointRisk(null);
    setUploadFiles([]);
    setUploadStatus("");
    setUploadError("");
  }

  async function handleMapClick(latlng) {
    if (!latlng || !token) return;
    setSelectedPoint(latlng);
    setRiskLoading(true);
    setRiskError("");
    try {
      const risk = await getPointRisk(token, latlng.lat, latlng.lng);
      setPointRisk(risk);
    } catch (err) {
      setRiskError(err.message || "Не удалось рассчитать риск.");
      setPointRisk(null);
    } finally {
      setRiskLoading(false);
    }
  }

  async function handleUpload(event) {
    event.preventDefault();
    if (!uploadFiles.length || uploadLoading) return;
    setUploadLoading(true);
    setUploadError("");
    setUploadStatus("");
    try {
      const formData = new FormData();
      for (const file of uploadFiles) formData.append("files", file);
      const result = await uploadRoads(formData, token);
      setUploadStatus(`Загружено: ${(result.uploaded || []).join(", ")}`);
      setUploadFiles([]);
      loadRoads();
    } catch (err) {
      setUploadError(err.message || "Ошибка загрузки.");
    } finally {
      setUploadLoading(false);
    }
  }

  if (!token) {
    return <LoginScreen onSubmit={handleLogin} />;
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <LayoutDashboard size={18} />
          <div>
            <strong>SpaceVision</strong>
            <span>Заиграевский район · без ИИ</span>
          </div>
        </div>
        <nav className="menu">
          {menuItems.map((item) => {
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
            <p>Заиграевский район: карта риска пожаров (дороги из SHP).</p>
          </div>
          <div className="auth">
            <span className="user-badge">{username || "Пользователь"} ({role})</span>
            <button onClick={handleLogout}>Выйти</button>
          </div>
        </header>

        <main className="content">
          {activeTab === "maps" && (
            <section className="map-card">
              <div className="map-toolbar">
                <div>
                  <h2>Карта</h2>
                  <p style={{ margin: 0, color: "var(--text-muted)" }}>
                    Кликните по карте, чтобы рассчитать вероятность пожара в точке.
                  </p>
                </div>
                <div className="layer-switcher">
                  <button
                    className={baseLayer === "scheme" ? "layer-btn active" : "layer-btn"}
                    onClick={() => setBaseLayer("scheme")}
                  >
                    Схема
                  </button>
                  <button
                    className={baseLayer === "satellite" ? "layer-btn active" : "layer-btn"}
                    onClick={() => setBaseLayer("satellite")}
                  >
                    Спутник
                  </button>
                </div>
              </div>
              {roadsError && <p className="status">{roadsError}</p>}
              <div className="map">
                <MapContainer
                  center={DEFAULT_CENTER}
                  zoom={DEFAULT_ZOOM}
                  style={{ height: "100%", width: "100%" }}
                >
                  <MapClickHandler onClick={handleMapClick} />
                  <RoadsFitBounds data={roads} />
                  {baseLayer === "scheme" ? (
                    <TileLayer
                      attribution="&copy; OpenStreetMap contributors"
                      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    />
                  ) : (
                    <TileLayer
                      attribution="Tiles &copy; Esri"
                      url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                    />
                  )}
                  {roads && (
                    <GeoJSON data={roads} pathOptions={{ color: "#d97706", weight: 2.5, opacity: 0.9 }} />
                  )}
                  {selectedPoint && (
                    <Marker position={[selectedPoint.lat, selectedPoint.lng]}>
                      <Popup>
                        {riskLoading ? (
                          "Расчёт…"
                        ) : riskError ? (
                          riskError
                        ) : pointRisk ? (
                          <div>
                            <strong>
                              {riskEmoji(pointRisk.risk_level)} {riskLabel(pointRisk.risk_level)} —{" "}
                              {(pointRisk.fire_probability * 100).toFixed(1)}%
                            </strong>
                            <br />
                            Расстояние до дороги:{" "}
                            {pointRisk.road_distance_m != null
                              ? `${pointRisk.road_distance_m.toFixed(0)} м`
                              : "—"}
                            <br />
                            Влияние дороги I(R): {pointRisk.road_influence.toFixed(3)}
                            <br />
                            Базовая P_base: {(pointRisk.base_probability * 100).toFixed(1)}%
                            <br />
                            Итоговая P_fire: {(pointRisk.fire_probability * 100).toFixed(1)}%
                          </div>
                        ) : (
                          ""
                        )}
                      </Popup>
                    </Marker>
                  )}
                </MapContainer>
              </div>
            </section>
          )}

          {activeTab === "upload" && (
            <section className="grid">
              <article className="card">
                <h2>Загрузка SHP (дороги)</h2>
                <p style={{ color: "var(--text-muted)" }}>
                  Загрузите файлы shapefile: .shp, .shx, .dbf, .prj (и опционально .cpg).
                  Файл .prj обязателен — он содержит систему координат (CRS).
                </p>
                <form onSubmit={handleUpload} className="upload-form">
                  <input
                    type="file"
                    multiple
                    accept=".shp,.shx,.dbf,.prj,.cpg"
                    onChange={(event) => setUploadFiles(Array.from(event.target.files || []))}
                  />
                  {uploadFiles.length > 0 && (
                    <div className="history">
                      {uploadFiles.map((file, index) => (
                        <div className="history-item" key={index}>
                          <strong>{file.name}</strong>
                          <span>{(file.size / 1024).toFixed(1)} КБ</span>
                        </div>
                      ))}
                    </div>
                  )}
                  <button type="submit" disabled={uploadLoading || uploadFiles.length === 0}>
                    {uploadLoading ? "Загрузка…" : "Загрузить"}
                  </button>
                </form>
                {uploadStatus && <p className="status">{uploadStatus}</p>}
                {uploadError && <p style={{ color: "#b91c1c" }}>{uploadError}</p>}
              </article>

              <article className="card">
                <h2>Текущее состояние дорог</h2>
                {roadsStatus ? (
                  <div>
                    <p>{roadsStatus.uploaded ? "Дороги загружены." : "Дороги ещё не загружены."}</p>
                    {roadsStatus.files && roadsStatus.files.length > 0 ? (
                      <div className="history">
                        {roadsStatus.files.map((file) => (
                          <div className="history-item" key={file}>
                            <strong>{file}</strong>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p style={{ color: "var(--text-muted)" }}>Файлы не найдены.</p>
                    )}
                    <p style={{ fontSize: 12, color: "var(--text-muted)", wordBreak: "break-all" }}>
                      {roadsStatus.roads_shp}
                    </p>
                  </div>
                ) : (
                  <p style={{ color: "var(--text-muted)" }}>Загрузка информации…</p>
                )}
              </article>
            </section>
          )}

          {activeTab === "profile" && (
            <section className="grid">
              <article className="card">
                <h2>Личный кабинет</h2>
                <p>
                  <strong>Пользователь:</strong> {username}
                </p>
                <p>
                  <strong>Роль:</strong> {role}
                </p>
                <button onClick={handleLogout}>Выйти</button>
              </article>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}


