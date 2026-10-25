import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BrainCircuit,
  CheckCircle2,
  FileText,
  Flame,
  History,
  Image as ImageIcon,
  Info,
  Layers,
  LayoutDashboard,
  LogOut,
  Map as MapIcon,
  MapPinned,
  Menu,
  Route,
  ShieldCheck,
  Upload,
  UserRound,
  X,
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
  API_URL,
  classifyFireImage,
  clearRoads,
  getAnalyticsSummary,
  getFireModelStatus,
  getPointRisk,
  getRiskHistory,
  getRoads,
  getOsmRoads,
  getRoadsStatus,
  getSettlements,
  getUploads,
  login,
  preloadFireModel,
  uploadRoads,
  uploadTile,
} from "./api";

const NAV_ITEMS = [
  { key: "dashboard", label: "Обзор", icon: LayoutDashboard },
  { key: "map", label: "Карта риска", icon: MapIcon },
  { key: "roads", label: "Дороги", icon: Route },
  { key: "ai-fire", label: "ИИ-оценка снимка", icon: Flame },
  { key: "history", label: "История", icon: History },
  { key: "statistics", label: "Статистика", icon: BarChart3 },
  { key: "documents", label: "Документы", icon: FileText },
  { key: "profile", label: "Личный кабинет", icon: UserRound },
];

const DEFAULT_CENTER = [51.85, 108.27];
const DEFAULT_ZOOM = 9;

const TAB_META = {
  dashboard: {
    title: "Обзор",
    subtitle: "Сводка по снимкам, дорогам и расчётам риска",
  },
  map: {
    title: "Карта риска",
    subtitle: "Один модуль: формула или ИИ-модель",
  },
  roads: {
    title: "Дороги",
    subtitle: "SHP-слой района и распознавание дорог по космоснимкам",
  },
  "ai-fire": {
    title: "ИИ-оценка пожарной опасности",
    subtitle: "Предобученная модель SigLIP2 оценивает риск по снимку",
  },
  history: {
    title: "История",
    subtitle: "Расчёты риска и обработанные космоснимки",
  },
  statistics: {
    title: "Статистика",
    subtitle: "Показатели распознавания дорожной сети",
  },
  documents: {
    title: "Документы",
    subtitle: "Исторические материалы для объяснения риска",
  },
  profile: {
    title: "Личный кабинет",
    subtitle: "Учётная запись и сводка активности",
  },
};

const RISK_LABELS = {
  very_low: "Очень низкий",
  low: "Низкий",
  moderate: "Умеренный",
  elevated: "Повышенный",
  medium: "Средний",
  high: "Высокий",
};
const RISK_GROUPS = {
  high: ["high", "elevated"],
  medium: ["medium", "moderate"],
  low: ["low", "very_low"],
};
const ROLE_LABELS = { admin: "Администратор", viewer: "Оператор" };
const DISTANCE_SOURCE_LABELS = {
  map: "слой карты Leaflet",
  shp: "SHP",
  osm: "OSM (резерв)",
  manual: "задано вручную",
  none: "нет данных",
};

function riskGroup(level) {
  if (RISK_GROUPS.high.includes(level)) return "high";
  if (RISK_GROUPS.medium.includes(level)) return "medium";
  if (RISK_GROUPS.low.includes(level)) return "low";
  return null;
}

function RiskBadge({ level }) {
  const key = level && RISK_LABELS[level] ? level : "unknown";
  return (
    <span className={`risk-badge ${key}`}>
      {RISK_LABELS[level] || "Не рассчитан"}
    </span>
  );
}

function Alert({ type = "info", children }) {
  const Icon =
    type === "error" || type === "warning"
      ? AlertTriangle
      : type === "success"
        ? CheckCircle2
        : Info;
  return (
    <div className={`alert ${type}`} role={type === "error" ? "alert" : undefined}>
      <Icon size={16} />
      <div>{children}</div>
    </div>
  );
}

function EmptyState({ icon: Icon = Info, title, text, action }) {
  return (
    <div className="empty-state">
      <span className="empty-state-icon">
        <Icon size={22} />
      </span>
      {title && <strong>{title}</strong>}
      {text && <p>{text}</p>}
      {action}
    </div>
  );
}

function KpiCard({ icon: Icon, tone = "", label, value, hint }) {
  return (
    <div className="kpi-card">
      <span className={`kpi-icon ${tone}`}>
        <Icon size={20} />
      </span>
      <div className="kpi-body">
        <div className="kpi-label">{label}</div>
        <div className="kpi-value">{value}</div>
        {hint && <div className="kpi-hint">{hint}</div>}
      </div>
    </div>
  );
}

function RiskLegend() {
  return (
    <div className="map-legend">
      <span>
        <i className="low" /> Низкий
      </span>
      <span>
        <i className="medium" /> Средний
      </span>
      <span>
        <i className="high" /> Высокий
      </span>
    </div>
  );
}

function Dashboard({ analytics, uploads, riskHistory, username, onNavigate }) {
  const totalUploads = analytics?.total_uploads ?? uploads.length;
  const withMasks = analytics?.uploads_with_predictions ?? 0;
  const averageRoad = analytics?.average_road_percentage ?? 0;
  const coverage = analytics?.global_road_coverage ?? 0;
  const highRisk = riskHistory.filter((item) => riskGroup(item.risk_level) === "high").length;
  const mediumRisk = riskHistory.filter((item) => riskGroup(item.risk_level) === "medium").length;
  const riskTotal = riskHistory.length || 1;
  const recentUploads = uploads.slice(0, 5);
  const recentRisks = riskHistory.slice(0, 5);

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Добро пожаловать, {username || "оператор"}</h1>
          <p className="page-subtitle">
            Заиграевский район · мониторинг дорожной сети и риска лесных пожаров
          </p>
        </div>
        <button className="btn-primary" onClick={() => onNavigate("roads")}>
          <Upload size={16} /> Загрузить снимок
        </button>
      </div>

      <div className="kpi-row">
        <KpiCard
          icon={ImageIcon}
          label="Космоснимков"
          value={totalUploads}
          hint={`${withMasks} с готовой маской`}
        />
        <KpiCard
          icon={Route}
          tone="blue"
          label="Средняя доля дорог"
          value={`${averageRoad.toFixed(2)}%`}
          hint={`Покрытие по всем снимкам: ${coverage.toFixed(2)}%`}
        />
        <KpiCard
          icon={Activity}
          label="Расчётов риска"
          value={riskHistory.length}
          hint={`Средних: ${mediumRisk}`}
        />
        <KpiCard
          icon={Flame}
          tone="red"
          label="Высокий риск"
          value={highRisk}
          hint={highRisk ? "Требует внимания" : "Высоких рисков нет"}
        />
      </div>

      <div className="dashboard-grid">
        <div className="dashboard-main">
          <section className="card">
            <div className="card-head">
              <h2>Последние снимки</h2>
              <button className="btn-ghost btn-sm" onClick={() => onNavigate("history")}>
                Все снимки <ArrowRight size={14} />
              </button>
            </div>
            {recentUploads.length === 0 ? (
              <EmptyState
                icon={ImageIcon}
                title="Снимков пока нет"
                text="Загрузите космоснимок — нейросеть распознает дороги и построит маску."
                action={
                  <button className="btn-primary btn-sm" onClick={() => onNavigate("roads")}>
                    Загрузить первый снимок
                  </button>
                }
              />
            ) : (
              <div className="list">
                {recentUploads.map((upload) => (
                  <div className="list-row" key={upload.id}>
                    <span className="list-icon">
                      <ImageIcon size={16} />
                    </span>
                    <div className="list-main">
                      <div className="list-title">{upload.title || "Без названия"}</div>
                      <div className="list-sub">{formatDate(upload.created_at)}</div>
                    </div>
                    <div className="list-trailing">
                      {upload.mask_url ? "маска готова" : "без маски"}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Последние расчёты риска</h2>
              <button className="btn-ghost btn-sm" onClick={() => onNavigate("history")}>
                Вся история <ArrowRight size={14} />
              </button>
            </div>
            {recentRisks.length === 0 ? (
              <EmptyState
                icon={MapPinned}
                title="Расчётов ещё не было"
                text="Поставьте точку на карте риска — система рассчитает вероятность пожара и объяснит факторы."
                action={
                  <button className="btn-primary btn-sm" onClick={() => onNavigate("map")}>
                    Открыть карту риска
                  </button>
                }
              />
            ) : (
              <div className="list">
                {recentRisks.map((record) => (
                  <div className="list-row" key={record.id}>
                    <span className="list-icon">
                      <Flame size={16} />
                    </span>
                    <div className="list-main">
                      <div className="list-title">{record.summary}</div>
                      <div className="list-sub">{formatDate(record.created_at)}</div>
                    </div>
                    <RiskBadge level={record.risk_level} />
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        <aside className="dashboard-side">
          <section className="card">
            <div className="card-head">
              <h2>Быстрые действия</h2>
            </div>
            <div className="quick-actions">
              <button className="quick-action" onClick={() => onNavigate("roads")}>
                <span className="quick-action-icon">
                  <Upload size={17} />
                </span>
                <span className="quick-action-body">
                  <strong>Загрузить снимок</strong>
                  <span>U-Net распознает дороги</span>
                </span>
              </button>
              <button className="quick-action" onClick={() => onNavigate("map")}>
                <span className="quick-action-icon">
                  <MapPinned size={17} />
                </span>
                <span className="quick-action-body">
                  <strong>Рассчитать риск</strong>
                  <span>Формула или ИИ-модель</span>
                </span>
              </button>
              <button className="quick-action" onClick={() => onNavigate("ai-fire")}>
                <span className="quick-action-icon">
                  <Flame size={17} />
                </span>
                <span className="quick-action-body">
                  <strong>Оценить снимок</strong>
                  <span>Модель SigLIP2 по фото</span>
                </span>
              </button>
              <button className="quick-action" onClick={() => onNavigate("roads")}>
                <span className="quick-action-icon">
                  <Layers size={17} />
                </span>
                <span className="quick-action-body">
                  <strong>Обновить SHP</strong>
                  <span>Слой дорог района</span>
                </span>
              </button>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Распределение риска</h2>
            </div>
            {riskHistory.length === 0 ? (
              <p className="muted">Данных пока нет — рассчитайте первую точку.</p>
            ) : (
              <div className="risk-dist">
                {["high", "medium", "low"].map((level) => {
                  const count = riskHistory.filter(
                    (item) => riskGroup(item.risk_level) === level
                  ).length;
                  return (
                    <div className="risk-dist-row" key={level}>
                      <span>{RISK_LABELS[level]}</span>
                      <div className="risk-dist-track">
                        <div
                          className={`risk-dist-fill ${level}`}
                          style={{ width: `${(count / riskTotal) * 100}%` }}
                        />
                      </div>
                      <span className="risk-dist-value">{count}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </aside>
      </div>
    </>
  );
}

function formatDate(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString("ru-RU");
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

const PLACE_POINT_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="7"/><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/></svg>';

function PlacePointControl({ active, onToggle }) {
  const map = useMap();
  const buttonRef = useRef(null);
  const onToggleRef = useRef(onToggle);
  onToggleRef.current = onToggle;

  useEffect(() => {
    const Control = L.Control.extend({
      options: { position: "topleft" },
      onAdd() {
        const container = L.DomUtil.create(
          "div",
          "leaflet-control leaflet-bar place-point-control"
        );
        const button = L.DomUtil.create("a", "place-point-button");
        button.href = "#";
        button.title = "Поставить точку для расчёта";
        button.setAttribute("role", "button");
        button.setAttribute("aria-label", "Поставить точку для расчёта");
        button.innerHTML = PLACE_POINT_ICON;
        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);
        L.DomEvent.on(button, "click", (event) => {
          L.DomEvent.preventDefault(event);
          L.DomEvent.stopPropagation(event);
          onToggleRef.current();
        });
        buttonRef.current = button;
        container.appendChild(button);
        return container;
      },
    });
    const control = new Control();
    map.addControl(control);
    return () => {
      map.removeControl(control);
      buttonRef.current = null;
    };
  }, [map]);

  useEffect(() => {
    if (!buttonRef.current) return;
    buttonRef.current.classList.toggle("active", active);
    buttonRef.current.title = active
      ? "Режим установки точки включён — кликните по карте"
      : "Поставить точку для расчёта";
  }, [active]);

  return null;
}

function PieChart({ value, size = 130, color = "#1f70d1", background = "#e8effa", label }) {
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
    return (
      <EmptyState
        icon={BarChart3}
        title="Недостаточно данных"
        text="Для графика нужно минимум два обработанных космоснимка."
      />
    );
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

function formatPercent(value) {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value === 0) return "0";
  if (value < 0.0001) return "<0.0001";
  if (value < 0.01) return value.toFixed(4);
  return value.toFixed(2);
}

function formatVal(value) {
  if (value == null) return "—";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "—";
    if (value === 0) return "0";
    if (Math.abs(value) < 0.0001) return value.toExponential(2);
    if (Math.abs(value) >= 100) return value.toFixed(0);
    if (Math.abs(value) >= 1) return value.toFixed(2);
    return value.toFixed(4);
  }
  return String(value);
}

const EARTH_RADIUS_M = 6371008.8;

function haversineMeters(a, b) {
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const deltaLat = lat2 - lat1;
  const deltaLon = ((b.lng - a.lng) * Math.PI) / 180;
  const h =
    Math.sin(deltaLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

function localMeters(latlng, origin) {
  const lat0 = (origin.lat * Math.PI) / 180;
  return {
    x: ((latlng.lng - origin.lng) * Math.PI * EARTH_RADIUS_M * Math.cos(lat0)) / 180,
    y: ((latlng.lat - origin.lat) * Math.PI * EARTH_RADIUS_M) / 180,
  };
}

function pointToSegmentDistance(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) return Math.hypot(px - ax, py - ay);
  let t = ((px - ax) * dx + (py - ay) * dy) / lengthSquared;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function ringContainsPoint(point, ring) {
  if (!Array.isArray(ring) || ring.length < 3) return false;
  const x = point.lng;
  const y = point.lat;
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index++) {
    const [xi, yi] = ring[index];
    const [xj, yj] = ring[previous];
    const crosses = (yi > y) !== (yj > y);
    if (crosses && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function polygonContainsPoint(polygon, point) {
  if (!Array.isArray(polygon) || polygon.length === 0) return false;
  if (!ringContainsPoint(point, polygon[0])) return false;
  return !polygon.slice(1).some((hole) => ringContainsPoint(point, hole));
}

function lineStringDistanceMeters(coordinates, origin) {
  if (!Array.isArray(coordinates) || coordinates.length === 0) return Infinity;
  let minimum = Infinity;
  let previous = localMeters(
    { lat: coordinates[0][1], lng: coordinates[0][0] },
    origin
  );
  for (let index = 1; index < coordinates.length; index += 1) {
    const current = localMeters(
      { lat: coordinates[index][1], lng: coordinates[index][0] },
      origin
    );
    minimum = Math.min(
      minimum,
      pointToSegmentDistance(0, 0, previous.x, previous.y, current.x, current.y)
    );
    previous = current;
  }
  return minimum;
}

function geometryDistanceMeters(geometry, origin) {
  if (!geometry) return Infinity;
  const { type, coordinates } = geometry;
  if (type === "Point") {
    return haversineMeters(origin, {
      lat: coordinates[1],
      lng: coordinates[0],
    });
  }
  if (type === "MultiPoint") {
    return Math.min(
      ...coordinates.map(([lng, lat]) => haversineMeters(origin, { lat, lng }))
    );
  }
  if (type === "LineString") {
    return lineStringDistanceMeters(coordinates, origin);
  }
  if (type === "MultiLineString" || type === "Polygon") {
    if (type === "Polygon" && polygonContainsPoint(coordinates, origin)) return 0;
    return Math.min(
      ...coordinates.map((line) => lineStringDistanceMeters(line, origin))
    );
  }
  if (type === "MultiPolygon") {
    if (coordinates.some((polygon) => polygonContainsPoint(polygon, origin))) {
      return 0;
    }
    return Math.min(
      ...coordinates.flatMap((polygon) =>
        polygon.map((ring) => lineStringDistanceMeters(ring, origin))
      )
    );
  }
  if (type === "GeometryCollection") {
    return Math.min(
      ...(geometry.geometries || []).map((item) =>
        geometryDistanceMeters(item, origin)
      )
    );
  }
  return Infinity;
}

function geojsonNearestDistanceMeters(collection, latlng) {
  const features = collection?.features;
  if (!Array.isArray(features) || features.length === 0) return null;
  let minimum = Infinity;
  for (const feature of features) {
    const distance = geometryDistanceMeters(feature?.geometry, latlng);
    if (Number.isFinite(distance)) minimum = Math.min(minimum, distance);
  }
  return Number.isFinite(minimum) ? minimum : null;
}

function mapDistancesForPoint(latlng, roadsData, settlementsData) {
  return {
    roadDistanceM: geojsonNearestDistanceMeters(roadsData, latlng),
    settlementDistanceM: geojsonNearestDistanceMeters(settlementsData, latlng),
  };
}

function ExplanationView({ explanation }) {
  if (!explanation) return null;
  const base = explanation.base;
  const road = explanation.road;
  const finalBlock = explanation.final;

  return (
    <div className="explanation">
      {explanation.coordinates && (
        <div className="explanation-coords">
          Широта {explanation.coordinates.lat?.toFixed(4)}, долгота{" "}
          {explanation.coordinates.lon?.toFixed(4)}
        </div>
      )}

      {explanation.weather && (
        <div className="weather-note">
          <span>Погодный фактор</span>
          <strong>
            {explanation.weather.source === "nasa-power"
              ? `N=${formatVal(explanation.weather.index)}, FWI=${formatVal(explanation.weather.normalized)}`
              : "климатическая норма (NASA POWER недоступен)"}
          </strong>
        </div>
      )}

      <details className="explanation-details">
        <summary>Формула модели</summary>
        <div className="explanation-equation">{explanation.equation}</div>
      </details>

      {base && (
        <div className="explanation-block">
          <div className="explanation-block-head">
            <strong>{base.label}</strong>
            <span>{base.formula}</span>
            <em>{(base.result * 100).toFixed(2)}%</em>
          </div>
          <table className="explanation-factors">
            <tbody>
              {base.factors.map((factor, index) => (
                <tr key={index}>
                  <td>
                    <div>{factor.name}</div>
                    {factor.note && <div className="factor-note">{factor.note}</div>}
                  </td>
                  <td>
                    {factor.input != null ? `${formatVal(factor.input)} → ` : ""}
                    {formatVal(factor.value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {road && (
        <div className="explanation-block">
          <div className="explanation-block-head">
            <strong>{road.label}</strong>
            <span>{road.formula}</span>
            <em>{formatVal(road.result)}</em>
          </div>
          <div className="explanation-kv">
            <span>
              R (до дороги):{" "}
              {road.R != null ? `${road.R.toFixed(0)} м` : "—"}
            </span>
            <span>R0: {road.R0.toFixed(0)} м</span>
            <span>
              Источник:{" "}
              {road.source === "shp"
                ? "SHP"
                : road.source === "osm"
                  ? "OSM (резерв)"
                  : "нет данных"}
            </span>
          </div>
        </div>
      )}

      {finalBlock && (
        <div className="explanation-block">
          <div className="explanation-block-head">
            <strong>{finalBlock.label}</strong>
            <span>{finalBlock.formula}</span>
            <em>{(finalBlock.result * 100).toFixed(2)}%</em>
          </div>
          <table className="explanation-factors two-col">
            <tbody>
              {finalBlock.terms.map((term, index) => (
                <tr key={index}>
                  <td>{term.name}</td>
                  <td>{formatVal(term.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {finalBlock ? (
        <div className="explanation-risk">
          Вероятность возгорания в текущем пожароопасном сезоне:{" "}
          <strong>{(finalBlock.result * 100).toFixed(1)}%</strong>
        </div>
      ) : (
        <p className="muted">
          Расчёт сохранён в старом формате — подробное объяснение недоступно.
        </p>
      )}
    </div>
  );
}

function AiExplanationView({ explanation }) {
  if (!explanation || explanation.method !== "ai") return null;
  const ai = explanation.ai;
  const finalBlock = explanation.final;
  if (!ai || !finalBlock) return null;

  return (
    <div className="explanation ai-explanation">
      {explanation.coordinates && (
        <div className="explanation-coords">
          Широта {explanation.coordinates.lat?.toFixed(4)}, долгота{" "}
          {explanation.coordinates.lon?.toFixed(4)}
        </div>
      )}

      <details className="explanation-details" open>
        <summary>Как получена ИИ-оценка</summary>
        <div className="explanation-equation">{explanation.equation}</div>
      </details>

      <div className="ai-point-card">
        {ai.tile?.url && (
          <img
            className="ai-point-tile"
            src={ai.tile.url}
            alt="Космоснимок участка для ИИ-оценки"
            loading="lazy"
          />
        )}
        <div className="ai-point-main">
          <span className="ai-point-label">Класс модели</span>
          <strong>{ai.predicted_ru}</strong>
          <span className="muted">
            Уверенность {((ai.confidence || 0) * 100).toFixed(1)}%
          </span>
          <div className="ai-point-score">
            <span>Индекс риска</span>
            <strong>{Math.round((ai.risk_score || 0) * 100)}%</strong>
          </div>
          <span className="ai-point-model">{ai.model_id}</span>
        </div>
      </div>

      <div className="fire-prob-list ai-point-probs">
        {(ai.probabilities || []).map((item) => (
          <div className="fire-prob-row" key={item.label}>
            <span>{item.label_ru}</span>
            <div className="fire-prob-track">
              <div
                className="fire-prob-fill"
                style={{ width: `${Math.max(item.probability * 100, 1)}%` }}
              />
            </div>
            <span className="fire-prob-value">
              {(item.probability * 100).toFixed(1)}%
            </span>
          </div>
        ))}
      </div>

      <div className="explanation-block">
        <div className="explanation-block-head">
          <strong>{finalBlock.label}</strong>
          <span>{finalBlock.formula}</span>
          <em>{(finalBlock.result * 100).toFixed(2)}%</em>
        </div>
        <table className="explanation-factors two-col">
          <tbody>
            {finalBlock.terms.map((term, index) => (
              <tr key={index}>
                <td>{term.name}</td>
                <td>{formatVal(term.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="explanation-risk">
        Вероятность возгорания в текущем пожароопасном сезоне:{" "}
        <strong>{(finalBlock.result * 100).toFixed(1)}%</strong>
      </div>
      <p className="ai-point-note">
        Оценка по снимку участка носит вспомогательный характер и не заменяет
        официальный прогноз пожарной опасности.
      </p>
    </div>
  );
}

function FormulaExplanationView({ explanation }) {
  if (!explanation || explanation.method !== "formula") return null;
  const inputs = explanation.inputs;
  const parameters = explanation.parameters;
  const result = explanation.result;
  const sources = explanation.distance_sources;
  if (!inputs || !result) return null;

  const parameterRows = [
    ["λ₀", "lambda0"],
    ["β", "beta"],
    ["γ", "gamma"],
  ];

  return (
    <div className="explanation formula-explanation">
      <div className="formula-result-card">
        <span>Вероятность пожара за год</span>
        <strong>{formatPercent(result.percent)}%</strong>
        <small>
          λ = {formatVal(result.lambda_per_ha_year)} пож./(га·год)
        </small>
      </div>

      <details className="explanation-details" open>
        <summary>Формула и параметры</summary>
        <div className="explanation-equation">{explanation.equation}</div>
        <div className="explanation-kv">
          <span>До дороги: {inputs.road_distance_m?.toFixed(0)} м</span>
          <span>
            До населённого пункта: {inputs.settlement_distance_m?.toFixed(0)} м
          </span>
          <span>Площадь: {inputs.area_ha} га</span>
        </div>
        <table className="explanation-factors formula-params">
          <thead>
            <tr>
              <th>Параметр</th>
              <th>Значение</th>
              <th>Единица</th>
            </tr>
          </thead>
          <tbody>
            {parameterRows.map(([label, key]) => (
              <tr key={key}>
                <td>{label}</td>
                <td>{formatVal(parameters?.[key]?.value)}</td>
                <td>{parameters?.[key]?.unit || "—"}</td>
              </tr>
            ))}
            <tr>
              <td>A</td>
              <td>{formatVal(inputs.area_ha)}</td>
              <td>га</td>
            </tr>
          </tbody>
        </table>
      </details>

      {explanation.factors?.length > 0 && (
        <div className="explanation-block">
          <div className="explanation-block-head">
            <strong>Расчёт по шагам</strong>
            <em>{formatPercent(result.percent)}%</em>
          </div>
          <table className="explanation-factors">
            <tbody>
              {explanation.factors.map((factor) => (
                <tr key={factor.key}>
                  <td>
                    <div>{factor.label}</div>
                    <div className="factor-note">{factor.formula}</div>
                  </td>
                  <td>
                    {factor.input != null ? `${formatVal(factor.input)} → ` : ""}
                    {formatVal(factor.value)}
                    {factor.unit ? ` ${factor.unit}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {sources && (
        <div className="explanation-kv formula-sources">
          <span>
            Дороги: {DISTANCE_SOURCE_LABELS[sources.road] || sources.road}
          </span>
          <span>
            Населённые пункты:{" "}
            {DISTANCE_SOURCE_LABELS[sources.settlement] || sources.settlement}
          </span>
        </div>
      )}

      {explanation.risk_level && (
        <div className="formula-level">
          <RiskBadge level={explanation.risk_level.code} />
          <span>{explanation.risk_level.note}</span>
        </div>
      )}

      {explanation.assumptions?.length > 0 && (
        <details className="explanation-details">
          <summary>Допущения и ограничения</summary>
          <ul className="formula-assumptions">
            {explanation.assumptions.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </details>
      )}

      <div className="explanation-risk">
        Вероятность хотя бы одного пожара за год на {inputs.area_ha} га:{" "}
        <strong>{formatPercent(result.percent)}%</strong>
      </div>
    </div>
  );
}

function RiskHistoryItem({ record, expanded, onToggle }) {
  const isAi = record.explanation?.method === "ai";
  const isFormula = record.explanation?.method === "formula";
  const hasFormulaResult = isFormula && record.explanation?.result;
  return (
    <div className="risk-history-item">
      <button className="risk-history-summary" onClick={onToggle}>
        <span className="risk-history-summary-main">
          <span className={`method-badge ${isAi ? "ai" : "formula"}`}>
            {isAi ? "ИИ" : "Формула"}
          </span>
          {record.summary}
        </span>
        <span className="risk-history-date">{formatDate(record.created_at)}</span>
      </button>
      {expanded &&
        (isAi ? (
          <AiExplanationView explanation={record.explanation} />
        ) : hasFormulaResult ? (
          <FormulaExplanationView explanation={record.explanation} />
        ) : (
          <ExplanationView explanation={record.explanation} />
        ))}
    </div>
  );
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
      <div className="auth-hero">
        <div className="auth-logo">
          <span className="auth-logo-mark">
            <BrainCircuit size={22} />
          </span>
          SpaceVision
        </div>
        <h1>Мониторинг риска лесных пожаров по космоснимкам</h1>
        <p>
          Нейросетевое распознавание дорог, расчёт вероятности возгорания и
          объяснение каждого фактора — для Заиграевского района Республики Бурятия.
        </p>
        <ul className="auth-features">
          <li>
            <span className="feature-icon">
              <BrainCircuit size={16} />
            </span>
            Сегментация дорог нейросетью U-Net
          </li>
          <li>
            <span className="feature-icon">
              <MapPinned size={16} />
            </span>
            Карта риска: формула или ИИ-модель по точке
          </li>
          <li>
            <span className="feature-icon">
              <ShieldCheck size={16} />
            </span>
            Прозрачная формула и история расчётов
          </li>
        </ul>
      </div>

      <div className="auth-card">
        <h2>Вход в систему</h2>
        <p className="auth-subtitle">
          Используйте учётную запись оператора или администратора.
        </p>
        <form onSubmit={handleSubmit} className="auth-form">
          <label>
            Логин
            <input
              placeholder="Например, operator"
              value={credentials.username}
              onChange={(event) =>
                setCredentials((prev) => ({ ...prev, username: event.target.value }))
              }
              autoFocus
            />
          </label>
          <label>
            Пароль
            <input
              placeholder="••••••••"
              type="password"
              value={credentials.password}
              onChange={(event) =>
                setCredentials((prev) => ({ ...prev, password: event.target.value }))
              }
            />
          </label>
          {error && <p className="auth-error">{error}</p>}
          <button type="submit" className="btn-block">
            Войти
          </button>
        </form>
        <p className="auth-hint">
          Демо-доступ: <code>admin / admin123</code> · <code>operator / operator123</code>
        </p>
      </div>
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState(localStorage.getItem("token") || "");
  const [username, setUsername] = useState(localStorage.getItem("username") || "");
  const [role, setRole] = useState(localStorage.getItem("role") || "viewer");
  const [activeTab, setActiveTab] = useState("dashboard");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [baseLayer, setBaseLayer] = useState("scheme");
  const [riskMethod, setRiskMethod] = useState("formula");
  const [historyTab, setHistoryTab] = useState("risk");

  const [uploads, setUploads] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [aiStatus, setAiStatus] = useState("");
  const [aiError, setAiError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [tileForm, setTileForm] = useState({ title: "", z: "", x: "", y: "" });
  const [file, setFile] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [docFiles, setDocFiles] = useState([]);
  const [docStatus, setDocStatus] = useState("");

  const [fireFile, setFireFile] = useState(null);
  const [firePreview, setFirePreview] = useState("");
  const [fireResult, setFireResult] = useState(null);
  const [fireStatus, setFireStatus] = useState(null);
  const [fireError, setFireError] = useState("");
  const [fireLoading, setFireLoading] = useState(false);
  const [firePreloading, setFirePreloading] = useState(false);

  const [roads, setRoads] = useState(null);
  const [roadsError, setRoadsError] = useState("");
  const [roadsStatus, setRoadsStatus] = useState(null);
  const [osmRoads, setOsmRoads] = useState(null);
  const [settlements, setSettlements] = useState(null);
  const [settlementsError, setSettlementsError] = useState("");
  const settlementsRef = useRef({ data: null, lat: null, lon: null });
  const settlementsRequestRef = useRef(null);
  const [selectedPoint, setSelectedPoint] = useState(null);
  const [pointRisk, setPointRisk] = useState(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const [riskError, setRiskError] = useState("");
  const [placingPoint, setPlacingPoint] = useState(false);
  const [uploadFiles, setUploadFiles] = useState([]);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [riskHistory, setRiskHistory] = useState([]);
  const [expandedRiskId, setExpandedRiskId] = useState(null);

  const canUpload = Boolean(token);

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

  async function loadUploads() {
    if (!token) {
      setUploads([]);
      return;
    }
    try {
      const data = await getUploads(token);
      setUploads(data);
    } catch (error) {
      setAiError(`Не удалось получить загрузки: ${error.message}`);
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
      setAiError(`Не удалось получить аналитику: ${error.message}`);
    }
  }

  async function loadRiskHistory() {
    if (!token) {
      setRiskHistory([]);
      return;
    }
    try {
      const history = await getRiskHistory(token);
      setRiskHistory(Array.isArray(history) ? history : []);
    } catch {
      setRiskHistory([]);
    }
  }

  async function ensureOsmRoads(lat, lon) {
    if (!token) return null;
    try {
      const data = await getOsmRoads(token, lat, lon, 5000);
      setOsmRoads(data);
      return data;
    } catch {
      setOsmRoads(null);
      return null;
    }
  }

  async function ensureSettlements(lat, lon) {
    if (!token) return null;
    const cached = settlementsRef.current;
    if (
      cached.data &&
      cached.lat != null &&
      haversineMeters({ lat, lng: lon }, { lat: cached.lat, lng: cached.lon }) < 15000
    ) {
      return cached.data;
    }
    if (settlementsRequestRef.current) return settlementsRequestRef.current;
    const request = getSettlements(token, lat, lon, 40000)
      .then((data) => {
        const payload = data || { type: "FeatureCollection", features: [] };
        settlementsRef.current = { data: payload, lat, lon };
        setSettlements(payload);
        setSettlementsError("");
        return payload;
      })
      .catch((error) => {
        setSettlementsError(
          error.message ||
            "Не удалось загрузить населённые пункты для карты. Формула использует резервный источник."
        );
        return null;
      })
      .finally(() => {
        settlementsRequestRef.current = null;
      });
    settlementsRequestRef.current = request;
    return request;
  }

  useEffect(() => {
    if (!token || activeTab !== "map" || settlementsRef.current.data) {
      return undefined;
    }
    let cancelled = false;
    getSettlements(token, DEFAULT_CENTER[0], DEFAULT_CENTER[1], 40000)
      .then((data) => {
        if (cancelled || !data) return;
        settlementsRef.current = {
          data,
          lat: DEFAULT_CENTER[0],
          lon: DEFAULT_CENTER[1],
        };
        setSettlements(data);
        setSettlementsError("");
      })
      .catch((error) => {
        if (!cancelled) {
          setSettlementsError(
            error.message ||
              "Не удалось загрузить населённые пункты для карты. Формула использует резервный источник."
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, activeTab]);

  useEffect(() => {
    loadRoads();
    loadUploads();
    loadAnalytics();
    loadRiskHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (!fireFile) {
      setFirePreview("");
      return undefined;
    }
    const previewUrl = URL.createObjectURL(fireFile);
    setFirePreview(previewUrl);
    return () => URL.revokeObjectURL(previewUrl);
  }, [fireFile]);

  const needsFireStatus =
    activeTab === "ai-fire" || (activeTab === "map" && riskMethod === "ai");

  useEffect(() => {
    if (!needsFireStatus || !token) return undefined;
    let cancelled = false;
    setFireError("");
    getFireModelStatus(token)
      .then((status) => {
        if (!cancelled) setFireStatus(status);
      })
      .catch((error) => {
        if (!cancelled) {
          setFireError(error.message || "Не удалось получить статус модели.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [needsFireStatus, token]);

  useEffect(() => {
    if (!needsFireStatus || !token || fireStatus?.state !== "loading") {
      return undefined;
    }
    const timer = setTimeout(() => {
      getFireModelStatus(token)
        .then((status) => setFireStatus(status))
        .catch((error) => setFireError(error.message || "Не удалось получить статус модели."));
    }, 3000);
    return () => clearTimeout(timer);
  }, [needsFireStatus, token, fireStatus]);

  function handleLogin(result) {
    localStorage.setItem("token", result.access_token);
    localStorage.setItem("role", result.role);
    localStorage.setItem("username", result.username);
    setToken(result.access_token);
    setRole(result.role);
    setUsername(result.username);
    setActiveTab("dashboard");
    setMobileNavOpen(false);
  }

  function handleLogout() {
    localStorage.removeItem("token");
    localStorage.removeItem("role");
    localStorage.removeItem("username");
    setToken("");
    setRole("viewer");
    setUsername("");
    setActiveTab("dashboard");
    setMobileNavOpen(false);
    setRoads(null);
    setRoadsStatus(null);
    setSettlements(null);
    setSettlementsError("");
    settlementsRef.current = { data: null, lat: null, lon: null };
    setOsmRoads(null);
    setSelectedPoint(null);
    setPointRisk(null);
    setPlacingPoint(false);
    setUploadFiles([]);
    setUploadStatus("");
    setUploadError("");
    setUploads([]);
    setAnalytics(null);
    setAiStatus("");
    setFile(null);
    setDocFiles([]);
    setDocStatus("");
    setFireFile(null);
    setFireResult(null);
    setFireStatus(null);
    setFireError("");
    setFireLoading(false);
    setFirePreloading(false);
  }

  function goTo(tab) {
    setActiveTab(tab);
    setMobileNavOpen(false);
  }

  async function calculateRisk(latlng, method = riskMethod) {
    if (!latlng || !token) return;
    setRiskLoading(true);
    setRiskError("");
    setPointRisk(null);
    try {
      let distances = {};
      if (method === "formula") {
        // Distances are measured in the Leaflet module against the layers
        // displayed on the map; the backend receives the two values.
        // Without an uploaded SHP roads layer, the roads come from OSM around the point.
        const roadsData = roads || (await ensureOsmRoads(latlng.lat, latlng.lng));
        const settlementsData =
          settlementsRef.current.data ||
          (await ensureSettlements(latlng.lat, latlng.lng));
        distances = mapDistancesForPoint(latlng, roadsData, settlementsData);
      }
      const risk = await getPointRisk(
        token,
        latlng.lat,
        latlng.lng,
        method,
        1,
        distances
      );
      setPointRisk(risk);
      loadRiskHistory();
    } catch (err) {
      const aborted = err?.name === "AbortError";
      setRiskError(
        aborted
          ? "Превышено время ожидания ответа. Попробуйте ещё раз."
          : err.message || "Не удалось рассчитать риск."
      );
    } finally {
      setRiskLoading(false);
    }
  }

  async function handleMapClick(latlng) {
    if (!latlng || !token || !placingPoint) return;
    setPlacingPoint(false);
    setSelectedPoint(latlng);
    await calculateRisk(latlng, riskMethod);
  }

  function handleMethodChange(method) {
    if (method === riskMethod) return;
    setRiskMethod(method);
    if (selectedPoint) {
      calculateRisk(selectedPoint, method);
    }
  }

  async function handleFirePreload() {
    if (!token || firePreloading) return;
    setFirePreloading(true);
    setFireError("");
    try {
      const status = await preloadFireModel(token);
      setFireStatus(status);
    } catch (error) {
      setFireError(error.message || "Не удалось запустить загрузку модели.");
    } finally {
      setFirePreloading(false);
    }
  }

  async function handleFireClassify(event) {
    event.preventDefault();
    if (!fireFile || fireLoading) return;
    setFireLoading(true);
    setFireError("");
    setFireResult(null);
    try {
      const formData = new FormData();
      formData.append("file", fireFile);
      const result = await classifyFireImage(formData, token);
      setFireResult(result);
    } catch (error) {
      setFireError(error.message || "Не удалось оценить снимок.");
    } finally {
      setFireLoading(false);
    }
  }

  function handleDocUpload(event) {
    event.preventDefault();
    if (!docFiles.length) {
      setDocStatus("Выберите файлы документов.");
      return;
    }
    setDocStatus("Заготовка: загрузка документов будет подключена позже.");
    setDocFiles([]);
  }

  async function handleUploadSHP(event) {
    event.preventDefault();
    if (!uploadFiles.length || uploadLoading) return;
    setUploadLoading(true);
    setUploadError("");
    setUploadStatus("");
    try {
      const formData = new FormData();
      for (const item of uploadFiles) formData.append("files", item);
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

  async function handleClearRoads() {
    if (!token) return;
    try {
      const result = await clearRoads(token);
      const removed = result.removed || [];
      setUploadStatus(removed.length ? `Удалено: ${removed.join(", ")}` : "Файлы дорог не найдены.");
      setUploadError("");
      setUploadFiles([]);
      loadRoads();
    } catch (err) {
      setUploadError(err.message || "Не удалось очистить дороги.");
    }
  }

  async function handleUploadTile(event) {
    event.preventDefault();
    if (!file) {
      setAiError("Выберите PNG/JPG файл тайла.");
      return;
    }
    setAiError("");
    setAiStatus("");
    setIsLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("title", tileForm.title);
      formData.append("tile_z", tileForm.z);
      formData.append("tile_x", tileForm.x);
      formData.append("tile_y", tileForm.y);
      const uploaded = await uploadTile(formData, token);
      setAiStatus(
        uploaded?.mask_url
          ? "Снимок загружен. Дороги распознаны, маска готова."
          : "Снимок загружен."
      );
      setFile(null);
      setTileForm({ title: "", z: "", x: "", y: "" });
      await loadUploads();
      await loadAnalytics();
      setHistoryTab("uploads");
      goTo("history");
    } catch (error) {
      setAiError(`Ошибка загрузки: ${error.message}`);
    } finally {
      setIsLoading(false);
    }
  }

  if (!token) {
    return <LoginScreen onSubmit={handleLogin} />;
  }

  const activeMeta = TAB_META[activeTab] || TAB_META.dashboard;
  const roleLabel = ROLE_LABELS[role] || role;
  const userInitials = (username || "?").slice(0, 2).toUpperCase();

  return (
    <div className="layout">
      <div
        className={mobileNavOpen ? "sidebar-backdrop visible" : "sidebar-backdrop"}
        onClick={() => setMobileNavOpen(false)}
        aria-hidden="true"
      />
      <aside
        className={[
          "sidebar",
          sidebarCollapsed ? "collapsed" : "",
          mobileNavOpen ? "open" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <div className="sidebar-top">
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed((prev) => !prev)}
            title={sidebarCollapsed ? "Развернуть меню" : "Свернуть меню"}
          >
            <Menu size={20} />
          </button>
          <div className="brand">
            <span className="brand-mark">
              <LayoutDashboard size={18} />
            </span>
            <div>
              <strong>SpaceVision</strong>
              <span>Карта риска + ИИ</span>
            </div>
          </div>
          <button
            className="sidebar-toggle sidebar-close"
            onClick={() => setMobileNavOpen(false)}
            title="Закрыть меню"
          >
            <X size={18} />
          </button>
        </div>
        <nav className="menu">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                className={activeTab === item.key ? "menu-link active" : "menu-link"}
                onClick={() => goTo(item.key)}
              >
                <span className="menu-left">
                  <Icon size={18} />
                  <span className="menu-label">{item.label}</span>
                </span>
              </button>
            );
          })}
        </nav>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="icon-btn mobile-menu-btn"
              onClick={() => setMobileNavOpen(true)}
              aria-label="Открыть меню"
            >
              <Menu size={20} />
            </button>
            <div className="topbar-title">
              <h1>{activeMeta.title}</h1>
              <p>{activeMeta.subtitle}</p>
            </div>
          </div>
          <div className="topbar-right">
            <div className="user-chip" title={`${username || "Пользователь"} · ${roleLabel}`}>
              <span className="avatar">{userInitials}</span>
              <span className="user-meta">
                <strong>{username || "Пользователь"}</strong>
                <span>{roleLabel}</span>
              </span>
            </div>
            <button className="icon-btn" onClick={handleLogout} title="Выйти" aria-label="Выйти">
              <LogOut size={18} />
            </button>
          </div>
        </header>

        <main className="content">
          {activeTab === "dashboard" && (
            <Dashboard
              analytics={analytics}
              uploads={safeUploads}
              riskHistory={riskHistory}
              username={username}
              onNavigate={goTo}
            />
          )}

          {activeTab === "map" && (
            <section className="map-card">
              <div className="map-toolbar">
                <div>
                  <h2>Карта риска</h2>
                  <p className="muted">
                    Поставьте точку — расстояния до дороги и населённого пункта
                    измеряются по слоям карты, затем рассчитывается вероятность.
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

              {roadsError && (
                <Alert type="warning">
                  <p>
                    <strong>Дороги из SHP ещё не загружены.</strong> Расстояние до
                    дороги вычисляется по слою карты; пока слой недоступен,
                    используется резервный источник OSM. Для точного расчёта
                    загрузите shapefile (.shp, .shx, .dbf, .prj) во вкладке
                    «Дороги».
                  </p>
                  <p className="roads-hint-detail">{roadsError}</p>
                  <button className="btn-sm" onClick={() => goTo("roads")}>
                    Перейти к загрузке SHP
                  </button>
                </Alert>
              )}

              {settlementsError && (
                <Alert type="warning">
                  <p>
                    <strong>Слой населённых пунктов недоступен.</strong>{" "}
                    Расстояние до населённого пункта будет взято из резервного
                    источника OSM. {settlementsError}
                  </p>
                </Alert>
              )}

              <div className="map-with-explanation">
                <div className="map">
                  <MapContainer
                    center={DEFAULT_CENTER}
                    zoom={DEFAULT_ZOOM}
                    style={{ height: "100%", width: "100%" }}
                  >
                    <MapClickHandler onClick={handleMapClick} />
                    <PlacePointControl
                      active={placingPoint}
                      onToggle={() => setPlacingPoint((prev) => !prev)}
                    />
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
                    {!roads && osmRoads?.features?.length > 0 && (
                      <GeoJSON
                        data={osmRoads}
                        pathOptions={{ color: "#f59e0b", weight: 2, opacity: 0.8, dashArray: "4 4" }}
                      />
                    )}
                    {settlements?.features?.length > 0 && (
                      <GeoJSON
                        data={settlements}
                        pointToLayer={(_feature, latlng) =>
                          L.circleMarker(latlng, {
                            radius: 4,
                            color: "#1d4ed8",
                            weight: 1,
                            fillColor: "#60a5fa",
                            fillOpacity: 0.9,
                          })
                        }
                        style={{ color: "#1d4ed8", weight: 1, fillOpacity: 0.75 }}
                      />
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
                                {formatPercent(pointRisk.fire_probability * 100)}% ·{" "}
                                {pointRisk.method === "ai"
                                  ? "ИИ-модель"
                                  : "формула"}
                              </strong>
                              <div style={{ margin: "6px 0" }}>
                                <RiskBadge level={pointRisk.risk_level} />
                              </div>
                              До дороги:{" "}
                              {pointRisk.road_distance_m != null
                                ? `${pointRisk.road_distance_m.toFixed(0)} м`
                                : "—"}
                              <br />
                              До поселения:{" "}
                              {pointRisk.settlement_distance_m != null
                                ? `${pointRisk.settlement_distance_m.toFixed(0)} м`
                                : "—"}
                              <br />
                              {pointRisk.method === "ai" ? (
                                <>
                                  Класс:{" "}
                                  {pointRisk.explanation?.ai?.predicted_ru || "—"}
                                  <br />
                                  Уверенность:{" "}
                                  {(
                                    (pointRisk.explanation?.ai?.confidence || 0) * 100
                                  ).toFixed(1)}
                                  %
                                </>
                              ) : (
                                <>
                                  λ:{" "}
                                  {formatVal(
                                    pointRisk.explanation?.result
                                      ?.lambda_per_ha_year
                                  )}{" "}
                                  пож./(га·год)
                                  <br />
                                  P:{" "}
                                  {formatPercent(
                                    pointRisk.explanation?.result?.percent
                                  )}
                                  %
                                </>
                              )}
                            </div>
                          ) : (
                            ""
                          )}
                        </Popup>
                      </Marker>
                    )}
                  </MapContainer>
                  <RiskLegend />
                </div>

                <aside className="explanation-panel">
                  <div className="method-picker">
                    <span className="method-picker-label">Метод расчёта</span>
                    <div className="method-toggle">
                      <button
                        className={
                          riskMethod === "formula" ? "method-btn active" : "method-btn"
                        }
                        onClick={() => handleMethodChange("formula")}
                      >
                        <Activity size={15} /> Формула
                      </button>
                      <button
                        className={riskMethod === "ai" ? "method-btn active" : "method-btn"}
                        onClick={() => handleMethodChange("ai")}
                      >
                        <BrainCircuit size={15} /> ИИ-модель
                      </button>
                    </div>
                    <p className="method-note">
                      {riskMethod === "formula"
                        ? "Годовая вероятность по расстояниям до дороги и населённого пункта, измеренным на карте."
                        : "Классификация космоснимка участка моделью SigLIP2. Результат отличается от формулы."}
                    </p>
                    {riskMethod === "ai" && (
                      <div className={`method-model-state ${fireStatus?.state || "unknown"}`}>
                        <span>
                          {!fireStatus
                            ? "Проверка ИИ-модели…"
                            : fireStatus.state === "ready"
                              ? "ИИ-модель готова"
                              : fireStatus.state === "loading"
                                ? "ИИ-модель загружается…"
                                : fireStatus.state === "disabled"
                                  ? "ИИ-модель отключена"
                                  : fireStatus.state === "error"
                                    ? fireStatus.error || "Ошибка загрузки модели"
                                    : "Модель ещё не подготовлена"}
                        </span>
                        {(fireStatus?.state === "not_loaded" ||
                          fireStatus?.state === "error") && (
                          <button
                            className="btn-primary btn-sm"
                            onClick={handleFirePreload}
                            disabled={firePreloading}
                          >
                            {firePreloading ? "Запуск…" : "Подготовить"}
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  {riskLoading ? (
                    <div className="explanation-placeholder">
                      <span className="spinner lg" />
                      {riskMethod === "ai"
                        ? "Классификация космоснимка участка…"
                        : "Расчёт вероятности по слоям карты…"}
                    </div>
                  ) : riskError ? (
                    <div className="explanation-placeholder error">
                      <span>{riskError}</span>
                      {selectedPoint && (
                        <button
                          className="btn-primary btn-sm"
                          onClick={() => calculateRisk(selectedPoint, riskMethod)}
                        >
                          Повторить расчёт
                        </button>
                      )}
                    </div>
                  ) : pointRisk ? (
                    <>
                      <div className={`risk-hero ${pointRisk.risk_level || "low"}`}>
                        <div className="risk-hero-value">
                          {formatPercent(pointRisk.fire_probability * 100)}%
                        </div>
                        <div className="risk-hero-meta">
                          <RiskBadge level={pointRisk.risk_level} />
                          <span>
                            {pointRisk.method === "ai"
                              ? "по снимку · текущий сезон"
                              : "по слоям карты · за год"}
                          </span>
                        </div>
                        <div className="risk-hero-facts">
                          <div className="risk-fact">
                            <span>До ближайшей дороги</span>
                            <strong>
                              {pointRisk.road_distance_m != null
                                ? `${pointRisk.road_distance_m.toFixed(0)} м`
                                : "—"}
                            </strong>
                          </div>
                          <div className="risk-fact">
                            <span>До поселения</span>
                            <strong>
                              {pointRisk.settlement_distance_m != null
                                ? `${pointRisk.settlement_distance_m.toFixed(0)} м`
                                : "—"}
                            </strong>
                          </div>
                          <div className="risk-fact">
                            <span>Метод</span>
                            <strong>
                              {pointRisk.method === "ai" ? "ИИ-модель" : "Формула"}
                            </strong>
                          </div>
                        </div>
                      </div>
                      {pointRisk.method === "ai" ? (
                        <AiExplanationView explanation={pointRisk.explanation} />
                      ) : (
                        <FormulaExplanationView explanation={pointRisk.explanation} />
                      )}
                    </>
                  ) : (
                    <div className="explanation-placeholder">
                      <span className="empty-state-icon">
                        {riskMethod === "ai" ? (
                          <BrainCircuit size={22} />
                        ) : (
                          <MapPinned size={22} />
                        )}
                      </span>
                      {riskMethod === "ai"
                        ? "Поставьте точку — модель классифицирует космоснимок участка."
                        : "Поставьте точку — расстояния до дороги и населённого пункта будут измерены по слоям карты."}
                    </div>
                  )}
                </aside>
              </div>
            </section>
          )}

          {activeTab === "roads" && (
            <section className="grid roads-grid">
              <article className="card">
                <h2>Дороги из Shapefile</h2>
                <p className="muted">
                  Загрузите .shp, .shx, .dbf и .prj (опционально .cpg). Файл .prj
                  обязателен: система не угадывает систему координат.
                </p>
                <form onSubmit={handleUploadSHP} className="upload-form">
                  <input
                    type="file"
                    multiple
                    accept=".shp,.shx,.dbf,.prj,.cpg"
                    onChange={(event) =>
                      setUploadFiles(Array.from(event.target.files || []))
                    }
                  />
                  {uploadFiles.length > 0 && (
                    <div className="history">
                      {uploadFiles.map((fileItem, index) => (
                        <div className="history-item" key={index}>
                          <strong>{fileItem.name}</strong>
                          <span>{(fileItem.size / 1024).toFixed(1)} КБ</span>
                        </div>
                      ))}
                    </div>
                  )}
                  <button
                    type="submit"
                    disabled={uploadLoading || uploadFiles.length === 0}
                  >
                    {uploadLoading ? "Загрузка…" : "Загрузить SHP"}
                  </button>
                </form>
                {uploadStatus && <p className="status">{uploadStatus}</p>}
                {uploadError && <p className="status error">{uploadError}</p>}
                <p className="muted">
                  После загрузки слой сразу используется на карте риска и в
                  расчёте плотности дорог.
                </p>
              </article>

              <article className="card">
                <h2>Текущий слой дорог</h2>
                {roadsStatus ? (
                  <div>
                    <p>
                      {roadsStatus.uploaded
                        ? "Дороги загружены."
                        : "Дороги ещё не загружены."}
                    </p>
                    {roadsStatus.files && roadsStatus.files.length > 0 ? (
                      <div className="history">
                        {roadsStatus.files.map((fileItem) => (
                          <div className="history-item" key={fileItem}>
                            <strong>{fileItem}</strong>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="muted">Файлы не найдены.</p>
                    )}
                    <p className="path-text">{roadsStatus.roads_shp}</p>
                    <button
                      type="button"
                      className="btn-danger"
                      onClick={handleClearRoads}
                      disabled={!roadsStatus.uploaded}
                    >
                      Очистить загруженные SHP
                    </button>
                  </div>
                ) : (
                  <div className="loading-block">
                    <span className="spinner" /> Загрузка информации…
                  </div>
                )}
              </article>

              <article className="card">
                <h2>Распознавание дорог по снимку</h2>
                <p className="muted">
                  Загрузите космоснимок — нейросеть U-Net построит маску дорог и
                  оверлей. Результат появится в истории снимков.
                </p>
                <form onSubmit={handleUploadTile} className="upload-form">
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
                    {isLoading ? "Распознавание…" : "Распознать дороги"}
                  </button>
                </form>
                {aiStatus && <Alert type="success">{aiStatus}</Alert>}
                {aiError && <Alert type="error">{aiError}</Alert>}
                <button
                  className="btn-ghost btn-sm"
                  onClick={() => {
                    setHistoryTab("uploads");
                    goTo("history");
                  }}
                >
                  <History size={15} /> История снимков
                </button>
              </article>

              <article className="card">
                <h2>Как это работает</h2>
                <div className="list">
                  <div className="list-row">
                    <span className="list-icon">
                      <Route size={16} />
                    </span>
                    <div className="list-main">
                      <div className="list-title">1. SHP-слой</div>
                      <div className="list-sub">
                        Дороги района для расстояний и плотности
                      </div>
                    </div>
                  </div>
                  <div className="list-row">
                    <span className="list-icon">
                      <BrainCircuit size={16} />
                    </span>
                    <div className="list-main">
                      <div className="list-title">2. Распознавание по снимку</div>
                      <div className="list-sub">
                        U-Net строит маску дорог и оверлей
                      </div>
                    </div>
                  </div>
                  <div className="list-row">
                    <span className="list-icon">
                      <BarChart3 size={16} />
                    </span>
                    <div className="list-main">
                      <div className="list-title">3. Аналитика</div>
                      <div className="list-sub">
                        Доля дорог и статистика по каждому снимку
                      </div>
                    </div>
                  </div>
                </div>
              </article>
            </section>
          )}

          {activeTab === "ai-fire" && (
            <section className="fire-layout">
              <article className="card">
                <div className="card-head">
                  <div>
                    <h2>Пожарная опасность по снимку</h2>
                    <p className="muted">
                      Загрузите космоснимок или фото участка — предобученная модель
                      определит класс пожарной опасности.
                    </p>
                  </div>
                  <span className="model-pill">
                    <Flame size={14} /> SigLIP2
                  </span>
                </div>

                <div className={`model-status ${fireStatus?.state || "unknown"}`}>
                  <span className="model-status-icon">
                    {fireStatus?.state === "ready" ? (
                      <CheckCircle2 size={18} />
                    ) : fireStatus?.state === "loading" ? (
                      <span className="spinner" />
                    ) : fireStatus?.state === "error" ? (
                      <AlertTriangle size={18} />
                    ) : (
                      <Info size={18} />
                    )}
                  </span>
                  <div className="model-status-body">
                    <strong>
                      {!fireStatus
                        ? "Проверка модели…"
                        : fireStatus.state === "ready"
                          ? "Модель готова"
                          : fireStatus.state === "loading"
                            ? "Загрузка модели…"
                            : fireStatus.state === "error"
                              ? "Модель не загрузилась"
                              : fireStatus.state === "disabled"
                                ? "Модель отключена"
                                : "Модель ещё не загружена"}
                    </strong>
                    <span>
                      {!fireStatus
                        ? "Проверяем состояние модели на сервере."
                        : fireStatus.state === "ready"
                          ? "Веса загружены — можно оценивать снимки."
                          : fireStatus.state === "loading"
                            ? "Первый запуск скачивает ~370 МБ. Это может занять несколько минут."
                            : fireStatus.state === "error"
                              ? fireStatus.error || "Не удалось загрузить веса модели."
                              : fireStatus.state === "disabled"
                                ? "На сервере установлено FIRE_RISK_MODEL_ENABLED=0."
                                : "Первый запуск скачает ~370 МБ и подготовит модель."}
                    </span>
                  </div>
                  {(fireStatus?.state === "not_loaded" ||
                    fireStatus?.state === "error") && (
                    <button
                      className="btn-primary btn-sm"
                      onClick={handleFirePreload}
                      disabled={firePreloading}
                    >
                      {firePreloading
                        ? "Запуск…"
                        : fireStatus.state === "error"
                          ? "Повторить"
                          : "Подготовить модель"}
                    </button>
                  )}
                </div>

                <form onSubmit={handleFireClassify} className="upload-form">
                  <input
                    type="file"
                    accept="image/*"
                    onChange={(event) => setFireFile(event.target.files?.[0] || null)}
                    disabled={fireLoading}
                  />
                  {firePreview && (
                    <div className="fire-preview">
                      <img src={firePreview} alt="Предпросмотр снимка" />
                    </div>
                  )}
                  <button
                    type="submit"
                    disabled={
                      !fireFile || fireLoading || fireStatus?.state !== "ready"
                    }
                  >
                    {fireLoading ? "Анализ снимка…" : "Оценить пожарную опасность"}
                  </button>
                </form>

                {fireError && <Alert type="error">{fireError}</Alert>}

                <p className="fire-model-note">
                  Модель: prithivMLmods/Fire-Risk-Detection (SigLIP2, Apache-2.0).
                  Она оценивает характер подстилающей поверхности на снимке, а не
                  прогнозирует возгорание в конкретной точке. Для точечного прогноза
                  используйте карту риска.
                </p>
              </article>

              <article className="card">
                <h2>Результат модели</h2>
                {!fireResult ? (
                  <EmptyState
                    icon={Flame}
                    title="Снимок ещё не оценён"
                    text="Выберите изображение и запустите оценку — здесь появятся класс пожарной опасности, уверенность модели и распределение вероятностей."
                  />
                ) : !fireResult.available ? (
                  <Alert type="warning">
                    {fireResult.reason || "Модель недоступна."}
                  </Alert>
                ) : (
                  <div className="fire-result">
                    <div className={`fire-hero ${fireResult.risk_level}`}>
                      <span className="fire-hero-icon">
                        <Flame size={26} />
                      </span>
                      <div className="fire-hero-main">
                        <span className="fire-hero-label">Класс модели</span>
                        <strong>{fireResult.predicted_ru}</strong>
                        <span className="muted">
                          Уверенность{" "}
                          {((fireResult.confidence || 0) * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="fire-score">
                        <strong>
                          {Math.round((fireResult.risk_score || 0) * 100)}%
                        </strong>
                        <span>индекс риска</span>
                      </div>
                    </div>

                    <div className="fire-facts">
                      <div>
                        <span>Уровень</span>
                        <RiskBadge level={fireResult.risk_level} />
                      </div>
                      <div>
                        <span>Модель</span>
                        <strong>{fireResult.model_id}</strong>
                      </div>
                    </div>

                    <div>
                      <h3>Распределение классов</h3>
                      <div className="fire-prob-list">
                        {(fireResult.probabilities || []).map((item) => (
                          <div className="fire-prob-row" key={item.label}>
                            <span>{item.label_ru}</span>
                            <div className="fire-prob-track">
                              <div
                                className="fire-prob-fill"
                                style={{
                                  width: `${Math.max(item.probability * 100, 1)}%`,
                                }}
                              />
                            </div>
                            <span className="fire-prob-value">
                              {(item.probability * 100).toFixed(1)}%
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>

                    <p className="fire-model-note">
                      Индекс риска — вероятностно взвешенная оценка классов
                      (от воды и негорючих поверхностей до очень высокой
                      опасности). Это вспомогательная оценка, а не официальный
                      прогноз.
                    </p>
                  </div>
                )}
              </article>
            </section>
          )}

          {activeTab === "documents" && (
            <section className="grid">
              <article className="card">
                <h2>Загрузка документов</h2>
                <p className="muted">
                  Заготовка модуля. Здесь будет загрузка исторических документов, которые ИИ
                  использует для объяснения процента риска.
                </p>
                <form onSubmit={handleDocUpload} className="upload-form">
                  <input
                    type="file"
                    multiple
                    accept=".pdf,.doc,.docx,.txt,.md,.json,.csv"
                    onChange={(event) => setDocFiles(Array.from(event.target.files || []))}
                  />
                  {docFiles.length > 0 && (
                    <div className="history">
                      {docFiles.map((fileItem, index) => (
                        <div className="history-item" key={index}>
                          <strong>{fileItem.name}</strong>
                          <span>{(fileItem.size / 1024).toFixed(1)} КБ</span>
                        </div>
                      ))}
                    </div>
                  )}
                  <button type="submit" disabled={docFiles.length === 0}>
                    Загрузить
                  </button>
                </form>
                {docStatus && <Alert type="info">{docStatus}</Alert>}
              </article>

              <article className="card">
                <h2>Зачем нужны документы</h2>
                <p className="muted">
                  Исторические отчёты, регламенты и сводки помогают ИИ объяснять расчёт
                  риска: какие факторы уже приводили к возгораниям в этом районе.
                </p>
                <div className="list">
                  <div className="list-row">
                    <span className="list-icon">
                      <FileText size={16} />
                    </span>
                    <div className="list-main">
                      <div className="list-title">Поддерживаемые форматы</div>
                      <div className="list-sub">PDF, DOC/DOCX, TXT, MD, JSON, CSV</div>
                    </div>
                  </div>
                  <div className="list-row">
                    <span className="list-icon">
                      <ShieldCheck size={16} />
                    </span>
                    <div className="list-main">
                      <div className="list-title">Прозрачность</div>
                      <div className="list-sub">Ссылки на источник в ответе ИИ</div>
                    </div>
                  </div>
                </div>
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
                  <EmptyState
                    icon={BarChart3}
                    title="Пока нет данных для рейтинга"
                    text="Загрузите космоснимки — рейтинг построится автоматически."
                    action={
                      <button className="btn-primary btn-sm" onClick={() => goTo("roads")}>
                        Загрузить снимок
                      </button>
                    }
                  />
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

          {activeTab === "history" && (
            <section className="card">
              <div className="history-head">
                <div>
                  <h2>История</h2>
                  <p className="muted">
                    Расчёты риска по точке и обработанные космоснимки.
                  </p>
                </div>
                <div className="tab-strip">
                  <button
                    className={historyTab === "risk" ? "tab-btn active" : "tab-btn"}
                    onClick={() => setHistoryTab("risk")}
                  >
                    Расчёты риска <span>{riskHistory.length}</span>
                  </button>
                  <button
                    className={historyTab === "uploads" ? "tab-btn active" : "tab-btn"}
                    onClick={() => setHistoryTab("uploads")}
                  >
                    Снимки <span>{safeUploads.length}</span>
                  </button>
                </div>
              </div>

              {historyTab === "risk" ? (
                riskHistory.length === 0 ? (
                  <EmptyState
                    icon={History}
                    title="Расчётов пока нет"
                    text="Поставьте точку на карте риска — система рассчитает вероятность пожара и объяснит факторы."
                    action={
                      <button className="btn-primary btn-sm" onClick={() => goTo("map")}>
                        Открыть карту риска
                      </button>
                    }
                  />
                ) : (
                  <div className="risk-history">
                    {riskHistory.map((record) => (
                      <RiskHistoryItem
                        key={record.id}
                        record={record}
                        expanded={expandedRiskId === record.id}
                        onToggle={() =>
                          setExpandedRiskId((prev) =>
                            prev === record.id ? null : record.id
                          )
                        }
                      />
                    ))}
                  </div>
                )
              ) : (
                <>
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
                      <EmptyState
                        icon={ImageIcon}
                        title="Ничего не найдено"
                        text="Измените фильтры или загрузите новый космоснимок."
                        action={
                          <button
                            className="btn-primary btn-sm"
                            onClick={() => goTo("roads")}
                          >
                            Загрузить снимок
                          </button>
                        }
                      />
                    ) : (
                      filteredUploads.map((upload) => {
                        const analyticsEntry = analyticsByUploadId.get(upload.id);
                        const roadPercent = analyticsEntry?.road_percentage ?? 0;
                        const clampedRoadPercent = Math.max(
                          0,
                          Math.min(100, roadPercent)
                        );
                        return (
                          <div
                            className="history-item"
                            key={upload.id ?? String(upload.title)}
                          >
                            <strong>{upload.title || "Без названия"}</strong>
                            <span>{formatDate(upload.created_at)}</span>
                            <span>
                              tile: z{upload.tile_z} / x{upload.tile_x} / y
                              {upload.tile_y}
                            </span>
                            <div className="history-road-metric">
                              <div className="history-road-metric-head">
                                <span>% пикселей дорог</span>
                                <strong>{clampedRoadPercent.toFixed(2)}%</strong>
                              </div>
                              <div className="history-road-bar-wrap">
                                <div
                                  className="history-road-bar"
                                  style={{
                                    width: `${Math.max(1, clampedRoadPercent)}%`,
                                  }}
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
                          </div>
                        );
                      })
                    )}
                  </div>
                </>
              )}
            </section>
          )}

          {activeTab === "profile" && (
            <section className="grid">
              <article className="card">
                <div className="profile-card">
                  <span className="profile-avatar">{userInitials}</span>
                  <div className="profile-info">
                    <strong>{username || "Пользователь"}</strong>
                    <span>{roleLabel}</span>
                  </div>
                </div>
                <div className="profile-rows">
                  <div className="profile-row">
                    <span>Роль</span>
                    <strong>{roleLabel}</strong>
                  </div>
                  <div className="profile-row">
                    <span>Космоснимков загружено</span>
                    <strong>{safeUploads.length}</strong>
                  </div>
                  <div className="profile-row">
                    <span>Расчётов риска</span>
                    <strong>{riskHistory.length}</strong>
                  </div>
                </div>
                <button className="btn-danger" onClick={handleLogout}>
                  <LogOut size={16} /> Выйти из системы
                </button>
              </article>

              <article className="card">
                <h2>Ваша активность</h2>
                <div className="profile-rows">
                  <div className="profile-row">
                    <span>Последний снимок</span>
                    <strong>{safeUploads[0]?.title || "—"}</strong>
                  </div>
                  <div className="profile-row">
                    <span>Дата загрузки</span>
                    <strong>{formatDate(safeUploads[0]?.created_at)}</strong>
                  </div>
                  <div className="profile-row">
                    <span>Последний расчёт риска</span>
                    <strong>{riskHistory[0]?.summary || "—"}</strong>
                  </div>
                  <div className="profile-row">
                    <span>Уровень риска</span>
                    <RiskBadge level={riskHistory[0]?.risk_level} />
                  </div>
                </div>
                <button className="btn-ghost" onClick={() => goTo("dashboard")}>
                  <LayoutDashboard size={16} /> На главную
                </button>
              </article>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}











