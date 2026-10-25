import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
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
  clearRoads,
  getAnalyticsSummary,
  getPointRisk,
  getRiskHistory,
  getRoads,
  getRoadsStatus,
  getUploads,
  login,
  uploadRoads,
  uploadTile,
} from "./api";

const modeMenus = [
  {
    key: "ai",
    label: "ИИ режим",
    icon: BrainCircuit,
    items: [
      { key: "ai-maps", label: "Карта космоснимков", icon: MapIcon },
      { key: "ai-upload", label: "Загрузка космоснимков", icon: Upload },
      { key: "ai-documents", label: "Загрузка документов", icon: FileText },
      { key: "ai-statistics", label: "Статистика", icon: BarChart3 },
      { key: "ai-history", label: "История загрузок", icon: History },
    ],
  },
  {
    key: "shape",
    label: "Shape режим",
    icon: Layers,
    items: [
      { key: "shape-maps", label: "Карта риска", icon: MapIcon },
      { key: "shape-upload", label: "Загрузка SHP", icon: Upload },
      { key: "shape-history", label: "История расчётов", icon: History },
    ],
  },
];

const DEFAULT_CENTER = [51.85, 108.27];
const DEFAULT_ZOOM = 9;

const TAB_META = {
  dashboard: {
    title: "Обзор",
    subtitle: "Сводка по снимкам, дорогам и расчётам риска",
  },
  "ai-maps": {
    title: "ИИ-режим · Карта космоснимков",
    subtitle: "Дистанционное зондирование и оценка риска по точке",
  },
  "ai-upload": {
    title: "ИИ-режим · Загрузка космоснимков",
    subtitle: "Автоматическое распознавание дорог нейросетью U-Net",
  },
  "ai-documents": {
    title: "ИИ-режим · Документы",
    subtitle: "Исторические материалы для объяснения риска",
  },
  "ai-statistics": {
    title: "ИИ-режим · Статистика",
    subtitle: "Показатели распознавания дорожной сети",
  },
  "ai-history": {
    title: "ИИ-режим · История загрузок",
    subtitle: "Обработанные снимки, маски и оверлеи",
  },
  "shape-maps": {
    title: "Shape-режим · Карта риска",
    subtitle: "Расчёт вероятности пожара по дорожной сети из Shapefile",
  },
  "shape-upload": {
    title: "Shape-режим · Загрузка SHP",
    subtitle: "Управление слоем дорог Заиграевского района",
  },
  "shape-history": {
    title: "Shape-режим · История расчётов",
    subtitle: "Все расчёты риска с полным объяснением",
  },
  profile: {
    title: "Личный кабинет",
    subtitle: "Учётная запись и сводка активности",
  },
};

const RISK_LABELS = { low: "Низкий", medium: "Средний", high: "Высокий" };
const ROLE_LABELS = { admin: "Администратор", viewer: "Оператор" };

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
  const highRisk = riskHistory.filter((item) => item.risk_level === "high").length;
  const mediumRisk = riskHistory.filter((item) => item.risk_level === "medium").length;
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
        <button className="btn-primary" onClick={() => onNavigate("ai-upload")}>
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
              <button className="btn-ghost btn-sm" onClick={() => onNavigate("ai-history")}>
                Все снимки <ArrowRight size={14} />
              </button>
            </div>
            {recentUploads.length === 0 ? (
              <EmptyState
                icon={ImageIcon}
                title="Снимков пока нет"
                text="Загрузите космоснимок — нейросеть распознает дороги и построит маску."
                action={
                  <button className="btn-primary btn-sm" onClick={() => onNavigate("ai-upload")}>
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
              <button className="btn-ghost btn-sm" onClick={() => onNavigate("shape-history")}>
                Вся история <ArrowRight size={14} />
              </button>
            </div>
            {recentRisks.length === 0 ? (
              <EmptyState
                icon={MapPinned}
                title="Расчётов ещё не было"
                text="Поставьте точку на карте риска — система рассчитает вероятность пожара и объяснит факторы."
                action={
                  <button className="btn-primary btn-sm" onClick={() => onNavigate("shape-maps")}>
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
              <button className="quick-action" onClick={() => onNavigate("ai-upload")}>
                <span className="quick-action-icon">
                  <Upload size={17} />
                </span>
                <span className="quick-action-body">
                  <strong>Загрузить снимок</strong>
                  <span>U-Net распознает дороги</span>
                </span>
              </button>
              <button className="quick-action" onClick={() => onNavigate("shape-maps")}>
                <span className="quick-action-icon">
                  <MapPinned size={17} />
                </span>
                <span className="quick-action-body">
                  <strong>Рассчитать риск</strong>
                  <span>Клик по точке на карте</span>
                </span>
              </button>
              <button className="quick-action" onClick={() => onNavigate("shape-upload")}>
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
                  const count = riskHistory.filter((item) => item.risk_level === level).length;
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

function formatVal(value) {
  if (value == null) return "—";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "—";
    if (Math.abs(value) >= 100) return value.toFixed(0);
    if (Math.abs(value) >= 1) return value.toFixed(2);
    return value.toFixed(4);
  }
  return String(value);
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

      <div className="explanation-risk">
        Вероятность пожара в течение года:{" "}
        <strong>{(explanation.final.result * 100).toFixed(1)}%</strong>
      </div>
    </div>
  );
}

function RiskHistoryItem({ record, expanded, onToggle }) {
  return (
    <div className="risk-history-item">
      <button className="risk-history-summary" onClick={onToggle}>
        <span>{record.summary}</span>
        <span className="risk-history-date">{formatDate(record.created_at)}</span>
      </button>
      {expanded && <ExplanationView explanation={record.explanation} />}
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
            Карта риска и расчёт по выбранной точке
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
  const [openMode, setOpenMode] = useState("shape");

  const [aiBaseLayer, setAiBaseLayer] = useState("scheme");
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
  const [aiPlacingPoint, setAiPlacingPoint] = useState(false);
  const [aiPoint, setAiPoint] = useState(null);
  const [docFiles, setDocFiles] = useState([]);
  const [docStatus, setDocStatus] = useState("");

  const [shapeBaseLayer, setShapeBaseLayer] = useState("scheme");
  const [roads, setRoads] = useState(null);
  const [roadsError, setRoadsError] = useState("");
  const [roadsStatus, setRoadsStatus] = useState(null);
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

  useEffect(() => {
    loadRoads();
    loadUploads();
    loadAnalytics();
    loadRiskHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

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
    setAiPoint(null);
    setAiPlacingPoint(false);
    setDocFiles([]);
    setDocStatus("");
  }

  function handleModeClick(modeKey) {
    if (sidebarCollapsed) {
      setSidebarCollapsed(false);
      setOpenMode(modeKey);
      return;
    }
    setOpenMode((prev) => (prev === modeKey ? "" : modeKey));
  }

  function goTo(tab) {
    setActiveTab(tab);
    setMobileNavOpen(false);
  }

  async function handleMapClick(latlng) {
    if (!latlng || !token || !placingPoint) return;
    setPlacingPoint(false);
    setSelectedPoint(latlng);
    setRiskLoading(true);
    setRiskError("");
    try {
      const risk = await getPointRisk(token, latlng.lat, latlng.lng);
      setPointRisk(risk);
      loadRiskHistory();
    } catch (err) {
      const aborted = err?.name === "AbortError";
      setRiskError(
        aborted
          ? "Превышено время ожидания ответа. Попробуйте ещё раз."
          : err.message || "Не удалось рассчитать риск."
      );
      setPointRisk(null);
    } finally {
      setRiskLoading(false);
    }
  }

  function handleAiMapClick(latlng) {
    if (!latlng || !aiPlacingPoint) return;
    setAiPoint({ lat: latlng.lat, lng: latlng.lng });
    setAiPlacingPoint(false);
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
      goTo("ai-history");
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
              <span>ИИ + Shape</span>
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
          <button
            className={activeTab === "dashboard" ? "menu-link active" : "menu-link"}
            onClick={() => goTo("dashboard")}
          >
            <span className="menu-left">
              <LayoutDashboard size={18} />
              <span className="menu-label">Обзор</span>
            </span>
          </button>

          {modeMenus.map((mode) => {
            const ModeIcon = mode.icon;
            const isOpen = openMode === mode.key;
            return (
              <div key={mode.key} className="mode-group">
                <button
                  className={isOpen ? "mode-header open" : "mode-header"}
                  onClick={() => handleModeClick(mode.key)}
                >
                  <span className="menu-left">
                    <ModeIcon size={18} />
                    <span className="menu-label">{mode.label}</span>
                  </span>
                  <ChevronDown
                    size={16}
                    className={isOpen ? "mode-chevron open" : "mode-chevron"}
                  />
                </button>
                {isOpen && (
                  <div className="submenu">
                    {mode.items.map((item) => {
                      const Icon = item.icon;
                      return (
                        <button
                          key={item.key}
                          className={activeTab === item.key ? "submenu-item active" : "submenu-item"}
                          onClick={() => goTo(item.key)}
                        >
                          <Icon size={16} />
                          <span>{item.label}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}

          <button
            className={activeTab === "profile" ? "menu-link active" : "menu-link"}
            onClick={() => goTo("profile")}
          >
            <span className="menu-left">
              <UserRound size={18} />
              <span className="menu-label">Личный кабинет</span>
            </span>
          </button>
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

          {activeTab === "ai-maps" && (
            <section className="card map-card">
              <div className="map-toolbar">
                <div>
                  <h2>Карта космоснимков</h2>
                  <p>
                    Нажмите кнопку-прицел и поставьте точку, чтобы получить оценку риска от ИИ.
                  </p>
                </div>
                <div className="layer-switcher">
                  <button
                    className={aiBaseLayer === "scheme" ? "layer-btn active" : "layer-btn"}
                    onClick={() => setAiBaseLayer("scheme")}
                  >
                    Схема
                  </button>
                  <button
                    className={aiBaseLayer === "satellite" ? "layer-btn active" : "layer-btn"}
                    onClick={() => setAiBaseLayer("satellite")}
                  >
                    Спутник
                  </button>
                </div>
              </div>
              <div className="map-with-explanation">
                <div className="map">
                  <MapContainer
                    center={DEFAULT_CENTER}
                    zoom={DEFAULT_ZOOM}
                    style={{ height: "100%", width: "100%" }}
                  >
                    <MapClickHandler onClick={handleAiMapClick} />
                    <PlacePointControl
                      active={aiPlacingPoint}
                      onToggle={() => setAiPlacingPoint((prev) => !prev)}
                    />
                    {aiBaseLayer === "scheme" ? (
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
                    <TileLayer url={`${API_URL}/tiles/{z}/{x}/{y}`} opacity={0.75} />
                    {aiPoint && (
                      <Marker position={[aiPoint.lat, aiPoint.lng]}>
                        <Popup>
                          Точка для расчёта риска (ИИ): {aiPoint.lat.toFixed(4)},{" "}
                          {aiPoint.lng.toFixed(4)}
                        </Popup>
                      </Marker>
                    )}
                  </MapContainer>
                  <RiskLegend />
                </div>

                <aside className="explanation-panel ai-answer-panel">
                  {aiPoint ? (
                    <>
                      <div className="explanation-panel-head">
                        <strong>Ответ ИИ</strong>
                      </div>
                      <div className="empty-state">
                        <span className="empty-state-icon">
                          <BrainCircuit size={22} />
                        </span>
                        <strong>Модуль в разработке</strong>
                        <p>
                          Точка: {aiPoint.lat.toFixed(4)}, {aiPoint.lng.toFixed(4)}.
                          Здесь появится оценка риска и объяснение на основе
                          исторических документов.
                        </p>
                      </div>
                    </>
                  ) : (
                    <div className="explanation-placeholder">
                      <span className="empty-state-icon">
                        <MapPinned size={22} />
                      </span>
                      Поставьте точку на карте, чтобы получить ответ ИИ.
                    </div>
                  )}
                </aside>
              </div>
            </section>
          )}

          {activeTab === "ai-upload" && (
            <section className="grid">
              <article className="card">
                <h2>Загрузка космоснимков</h2>
                <p className="muted">
                  Снимок будет обработан нейросетью: дороги распознаются автоматически.
                </p>
                <form onSubmit={handleUploadTile} className="upload-form">
                  <input
                    placeholder="Название снимка"
                    value={tileForm.title}
                    onChange={(event) => setTileForm((prev) => ({ ...prev, title: event.target.value }))}
                    disabled={!canUpload}
                  />
                  <div className="inputs-row">
                    <input
                      placeholder="z (опционально)"
                      value={tileForm.z}
                      onChange={(event) => setTileForm((prev) => ({ ...prev, z: event.target.value }))}
                      disabled={!canUpload}
                    />
                    <input
                      placeholder="x (опционально)"
                      value={tileForm.x}
                      onChange={(event) => setTileForm((prev) => ({ ...prev, x: event.target.value }))}
                      disabled={!canUpload}
                    />
                    <input
                      placeholder="y (опционально)"
                      value={tileForm.y}
                      onChange={(event) => setTileForm((prev) => ({ ...prev, y: event.target.value }))}
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
                    {isLoading ? "Загрузка…" : "Загрузить"}
                  </button>
                </form>
                {aiStatus && <Alert type="success">{aiStatus}</Alert>}
                {aiError && <Alert type="error">{aiError}</Alert>}
              </article>

              <article className="card">
                <h2>Как это работает</h2>
                <div className="list">
                  <div className="list-row">
                    <span className="list-icon">
                      <Upload size={16} />
                    </span>
                    <div className="list-main">
                      <div className="list-title">1. Загрузка снимка</div>
                      <div className="list-sub">PNG или JPEG; tile z/x/y — по желанию</div>
                    </div>
                  </div>
                  <div className="list-row">
                    <span className="list-icon">
                      <BrainCircuit size={16} />
                    </span>
                    <div className="list-main">
                      <div className="list-title">2. Распознавание дорог</div>
                      <div className="list-sub">Нейросеть U-Net строит маску и оверлей</div>
                    </div>
                  </div>
                  <div className="list-row">
                    <span className="list-icon">
                      <BarChart3 size={16} />
                    </span>
                    <div className="list-main">
                      <div className="list-title">3. Аналитика</div>
                      <div className="list-sub">Доля дорог и статистика по каждому снимку</div>
                    </div>
                  </div>
                </div>
              </article>
            </section>
          )}

          {activeTab === "ai-documents" && (
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

          {activeTab === "ai-statistics" && (
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
                      <button className="btn-primary btn-sm" onClick={() => goTo("ai-upload")}>
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

          {activeTab === "ai-history" && (
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
                  <EmptyState
                    icon={ImageIcon}
                    title="Ничего не найдено"
                    text="Измените фильтры или загрузите новый космоснимок."
                    action={
                      <button className="btn-primary btn-sm" onClick={() => goTo("ai-upload")}>
                        Загрузить снимок
                      </button>
                    }
                  />
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
                      </div>
                    );
                  })
                )}
              </div>
            </section>
          )}

          {activeTab === "shape-maps" && (
            <section className="map-card">
              <div className="map-toolbar">
                <div>
                  <h2>Карта</h2>
                  <p className="muted">
                    Нажмите кнопку-прицел, затем поставьте точку на карте.
                  </p>
                </div>
                <div className="layer-switcher">
                  <button
                    className={shapeBaseLayer === "scheme" ? "layer-btn active" : "layer-btn"}
                    onClick={() => setShapeBaseLayer("scheme")}
                  >
                    Схема
                  </button>
                  <button
                    className={shapeBaseLayer === "satellite" ? "layer-btn active" : "layer-btn"}
                    onClick={() => setShapeBaseLayer("satellite")}
                  >
                    Спутник
                  </button>
                </div>
              </div>
              {roadsError && (
                <Alert type="warning">
                  <p>
                    <strong>Дороги ещё не загружены.</strong> Чтобы рассчитывать
                    вероятность пожара, загрузите shapefile (.shp, .shx, .dbf, .prj) в
                    разделе «Загрузка SHP».
                  </p>
                  <p className="roads-hint-detail">{roadsError}</p>
                  <button className="btn-sm" onClick={() => goTo("shape-upload")}>
                    Перейти к загрузке SHP
                  </button>
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
                    {shapeBaseLayer === "scheme" ? (
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
                                {(pointRisk.fire_probability * 100).toFixed(1)}% в течение года
                              </strong>
                              <div style={{ margin: "6px 0" }}>
                                <RiskBadge level={pointRisk.risk_level} />
                              </div>
                              Расстояние до дороги:{" "}
                              {pointRisk.road_distance_m != null
                                ? `${pointRisk.road_distance_m.toFixed(0)} м`
                                : "—"}
                              <br />
                              Дорога I(R), учтена в P_base:{" "}
                              {pointRisk.road_influence.toFixed(3)}
                              <br />
                              Логит-модель P_base:{" "}
                              {(pointRisk.base_probability * 100).toFixed(1)}%
                              <br />
                              Итоговая P_fire:{" "}
                              {(pointRisk.fire_probability * 100).toFixed(1)}%
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
                  {riskLoading ? (
                    <div className="explanation-placeholder">
                      <span className="spinner lg" />
                      Расчёт вероятности…
                    </div>
                  ) : riskError ? (
                    <div className="explanation-placeholder error">{riskError}</div>
                  ) : pointRisk ? (
                    <>
                      <div className={`risk-hero ${pointRisk.risk_level || "low"}`}>
                        <div className="risk-hero-value">
                          {(pointRisk.fire_probability * 100).toFixed(1)}%
                        </div>
                        <div className="risk-hero-meta">
                          <RiskBadge level={pointRisk.risk_level} />
                          <span>в течение года</span>
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
                            <span>Источник дорог</span>
                            <strong>
                              {pointRisk.road_source === "shp"
                                ? "SHP"
                                : pointRisk.road_source === "osm"
                                  ? "OSM"
                                  : "—"}
                            </strong>
                          </div>
                        </div>
                      </div>
                      <ExplanationView explanation={pointRisk.explanation} />
                    </>
                  ) : (
                    <div className="explanation-placeholder">
                      <span className="empty-state-icon">
                        <MapPinned size={22} />
                      </span>
                      Нажмите кнопку-прицел и поставьте точку, чтобы увидеть подробное
                      объяснение расчёта.
                    </div>
                  )}
                </aside>
              </div>
            </section>
          )}

          {activeTab === "shape-history" && (
            <section className="card">
              <h2>История расчётов вероятности пожара</h2>
              {riskHistory.length === 0 ? (
                <EmptyState
                  icon={History}
                  title="Расчётов пока нет"
                  text="Поставьте точку на карте риска — система рассчитает вероятность пожара и объяснит факторы."
                  action={
                    <button className="btn-primary btn-sm" onClick={() => goTo("shape-maps")}>
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
                        setExpandedRiskId((prev) => (prev === record.id ? null : record.id))
                      }
                    />
                  ))}
                </div>
              )}
            </section>
          )}

          {activeTab === "shape-upload" && (
            <section className="grid">
              <article className="card">
                <h2>Загрузка SHP (дороги)</h2>
                <p className="muted">
                  Загрузите файлы shapefile: .shp, .shx, .dbf, .prj (и опционально .cpg).
                  Файл .prj обязателен — он содержит систему координат (CRS).
                </p>
                <form onSubmit={handleUploadSHP} className="upload-form">
                  <input
                    type="file"
                    multiple
                    accept=".shp,.shx,.dbf,.prj,.cpg"
                    onChange={(event) => setUploadFiles(Array.from(event.target.files || []))}
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
                  <button type="submit" disabled={uploadLoading || uploadFiles.length === 0}>
                    {uploadLoading ? "Загрузка…" : "Загрузить"}
                  </button>
                </form>
                {uploadStatus && <p className="status">{uploadStatus}</p>}
                {uploadError && <p className="status error">{uploadError}</p>}
              </article>

              <article className="card">
                <h2>Текущее состояние дорог</h2>
                {roadsStatus ? (
                  <div>
                    <p>{roadsStatus.uploaded ? "Дороги загружены." : "Дороги ещё не загружены."}</p>
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











