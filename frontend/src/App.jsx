import { useEffect, useState } from "react";
import L from "leaflet";
import {
  GeoJSON,
  MapContainer,
  Marker,
  Popup,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { getPointRisk, getRoads, login } from "./api";

// Fallback map centre for the Zaigraevsky district (Republic of Buryatia).
// Once the SHP roads are loaded, the map auto-fits to their extent.
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
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [30, 30] });
    }
  }, [data, map]);
  return null;
}

const authStyle = {
  minHeight: "100vh",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: "linear-gradient(135deg, #14532d, #1f7a4d)",
  fontFamily: "Inter, Segoe UI, Arial, sans-serif",
};

const cardStyle = {
  background: "#fff",
  borderRadius: 16,
  padding: 32,
  width: 360,
  boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
};

const inputStyle = {
  width: "100%",
  padding: "10px 12px",
  marginTop: 10,
  border: "1px solid #cde6d4",
  borderRadius: 8,
  fontSize: 14,
  boxSizing: "border-box",
};

const buttonStyle = {
  width: "100%",
  padding: "12px",
  marginTop: 18,
  background: "#1f7a4d",
  color: "#fff",
  border: "none",
  borderRadius: 8,
  fontSize: 15,
  fontWeight: 600,
  cursor: "pointer",
};

function LoginScreen({ onLogin }) {
  const [credentials, setCredentials] = useState({ username: "", password: "" });
  const [error, setError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    try {
      const result = await login(credentials.username, credentials.password);
      onLogin(result);
    } catch (err) {
      setError(err.message || "Неверный логин или пароль.");
    }
  }

  return (
    <div style={authStyle}>
      <form onSubmit={handleSubmit} style={cardStyle}>
        <h1 style={{ color: "#1f5b3a", margin: 0 }}>SpaceVision — Заиграевский район</h1>
        <p style={{ color: "#496a59", marginTop: 6 }}>
          Версия без нейросети: дороги загружаются из Shapefile (SHP).
        </p>
        <input
          style={inputStyle}
          placeholder="Логин"
          value={credentials.username}
          onChange={(e) => setCredentials({ ...credentials, username: e.target.value })}
          autoFocus
        />
        <input
          style={inputStyle}
          type="password"
          placeholder="Пароль"
          value={credentials.password}
          onChange={(e) => setCredentials({ ...credentials, password: e.target.value })}
        />
        {error && <p style={{ color: "#b91c1c", marginTop: 10 }}>{error}</p>}
        <button type="submit" style={buttonStyle}>
          Войти
        </button>
        <p style={{ color: "#7c9a88", fontSize: 12, marginTop: 14 }}>
          Демо-доступ: admin / admin123, operator / operator123
        </p>
      </form>
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState(localStorage.getItem("token") || "");
  const [username, setUsername] = useState(localStorage.getItem("username") || "");
  const [role, setRole] = useState(localStorage.getItem("role") || "viewer");

  const [baseLayer, setBaseLayer] = useState("scheme");
  const [roads, setRoads] = useState(null);
  const [roadsError, setRoadsError] = useState("");

  const [selectedPoint, setSelectedPoint] = useState(null);
  const [pointRisk, setPointRisk] = useState(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const [riskError, setRiskError] = useState("");

  useEffect(() => {
    if (!token) return;
    setRoadsError("");
    getRoads(token)
      .then((data) => setRoads(data))
      .catch((err) => setRoadsError(err.message || "Не удалось загрузить дороги."));
  }, [token]);

  function handleLogin(result) {
    localStorage.setItem("token", result.access_token);
    localStorage.setItem("role", result.role);
    localStorage.setItem("username", result.username);
    setToken(result.access_token);
    setRole(result.role);
    setUsername(result.username);
  }

  function handleLogout() {
    localStorage.removeItem("token");
    localStorage.removeItem("role");
    localStorage.removeItem("username");
    setToken("");
    setRole("viewer");
    setUsername("");
    setRoads(null);
    setSelectedPoint(null);
    setPointRisk(null);
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

  if (!token) {
    return <LoginScreen onLogin={handleLogin} />;
  }

  const firePercent = pointRisk ? pointRisk.fire_probability * 100 : null;

  return (
    <div style={{ fontFamily: "Inter, Segoe UI, Arial, sans-serif", minHeight: "100vh", background: "#f1f7f2" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 24px",
          background: "#1f7a4d",
          color: "#fff",
        }}
      >
        <div>
          <strong style={{ fontSize: 18 }}>Заиграевский район — риск лесных пожаров</strong>
          <span style={{ display: "block", fontSize: 12, opacity: 0.85 }}>
            Версия без нейросети · дороги из SHP · I(R)=1/(1+R/R0)
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ fontSize: 13 }}>
            {username} <span style={{ opacity: 0.7 }}>({role})</span>
          </span>
          <button
            onClick={handleLogout}
            style={{
              background: "rgba(255,255,255,0.15)",
              color: "#fff",
              border: "1px solid rgba(255,255,255,0.4)",
              borderRadius: 6,
              padding: "6px 12px",
              cursor: "pointer",
            }}
          >
            Выйти
          </button>
        </div>
      </header>

      <div style={{ padding: 16, maxWidth: 1200, margin: "0 auto" }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 10,
          }}
        >
          <p style={{ margin: 0, color: "#2d4d3b" }}>
            Кликните по карте, чтобы рассчитать вероятность пожара в точке.
          </p>
          <div>
            <button
              onClick={() => setBaseLayer("scheme")}
              style={{
                ...buttonStyle,
                width: "auto",
                margin: 0,
                marginRight: 6,
                background: baseLayer === "scheme" ? "#1f7a4d" : "#cde6d4",
                color: baseLayer === "scheme" ? "#fff" : "#2d4d3b",
              }}
            >
              Схема
            </button>
            <button
              onClick={() => setBaseLayer("satellite")}
              style={{
                ...buttonStyle,
                width: "auto",
                margin: 0,
                background: baseLayer === "satellite" ? "#1f7a4d" : "#cde6d4",
                color: baseLayer === "satellite" ? "#fff" : "#2d4d3b",
              }}
            >
              Спутник
            </button>
          </div>
        </div>

        {roadsError && (
          <p style={{ color: "#b91c1c", background: "#fdecea", padding: 10, borderRadius: 8 }}>
            {roadsError}
          </p>
        )}

        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 700px", borderRadius: 12, overflow: "hidden", boxShadow: "0 2px 12px rgba(0,0,0,0.08)" }}>
            <MapContainer
              center={DEFAULT_CENTER}
              zoom={DEFAULT_ZOOM}
              style={{ height: 560, width: "100%" }}
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
                <GeoJSON
                  data={roads}
                  pathOptions={{ color: "#d97706", weight: 2.5, opacity: 0.9 }}
                />
              )}
              {selectedPoint && (
                <Marker position={[selectedPoint.lat, selectedPoint.lng]}>
                  <Popup>
                    Точка риска
                    <br />
                    {selectedPoint.lat.toFixed(6)}, {selectedPoint.lng.toFixed(6)}
                  </Popup>
                </Marker>
              )}
            </MapContainer>
          </div>

          <aside style={{ flex: "1 1 320px", minWidth: 280 }}>
            <div style={{ background: "#fff", borderRadius: 12, padding: 18, boxShadow: "0 2px 12px rgba(0,0,0,0.08)" }}>
              <h3 style={{ marginTop: 0, color: "#1f5b3a" }}>Расчёт вероятности пожара</h3>
              {!selectedPoint && !riskLoading && (
                <p style={{ color: "#496a59" }}>Точка ещё не выбрана. Кликните по карте.</p>
              )}
              {riskLoading && <p style={{ color: "#496a59" }}>Расчёт…</p>}
              {riskError && <p style={{ color: "#b91c1c" }}>{riskError}</p>}
              {!riskLoading && pointRisk && (
                <div>
                  <p style={{ fontSize: 30, fontWeight: 700, color: "#1f5b3a", margin: "6px 0" }}>
                    {riskEmoji(pointRisk.risk_level)} {firePercent.toFixed(1)}%
                  </p>
                  <p style={{ margin: "4px 0", color: "#2d4d3b" }}>
                    Уровень: <strong>{riskLabel(pointRisk.risk_level)}</strong>
                  </p>
                  <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse", marginTop: 8 }}>
                    <tbody>
                      <Row label="Расстояние до дороги R" value={pointRisk.road_distance_m != null ? `${pointRisk.road_distance_m.toFixed(0)} м` : "—"} />
                      <Row label="Влияние дороги I(R)" value={pointRisk.road_influence.toFixed(3)} />
                      <Row label="Базовая вероятность P_base" value={`${(pointRisk.base_probability * 100).toFixed(1)}%`} />
                      <Row label="Итоговая P_fire" value={`${firePercent.toFixed(1)}%`} />
                    </tbody>
                  </table>
                  <p style={{ color: "#496a59", fontSize: 12, marginTop: 10 }}>
                    {pointRisk.risk_reason}
                  </p>
                </div>
              )}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <tr>
      <td style={{ padding: "4px 0", color: "#496a59" }}>{label}</td>
      <td style={{ padding: "4px 0", textAlign: "right", fontWeight: 600, color: "#1f5b3a" }}>{value}</td>
    </tr>
  );
}



