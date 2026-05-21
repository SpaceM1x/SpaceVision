import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";
import "leaflet/dist/leaflet.css";

class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, message: error?.message || "Неизвестная ошибка интерфейса." };
  }

  componentDidCatch(error) {
    console.error("UI crashed:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 24, fontFamily: "Inter, Segoe UI, Arial, sans-serif" }}>
          <h2 style={{ color: "#1f5b3a", marginBottom: 10 }}>Ошибка интерфейса</h2>
          <p style={{ color: "#496a59" }}>
            Произошла ошибка рендера. Обновите страницу или перезапустите frontend.
          </p>
          <pre
            style={{
              background: "#f6fbf6",
              border: "1px solid #cde6d4",
              borderRadius: 8,
              padding: 12,
              overflowX: "auto",
              color: "#2d4d3b",
            }}
          >
            {this.state.message}
          </pre>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("app")).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </React.StrictMode>,
);
