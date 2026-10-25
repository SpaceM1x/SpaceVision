const API_URL =
  import.meta.env.VITE_API_URL || `${window.location.protocol}//${window.location.hostname}:8000`;

async function parseResponse(response) {
  if (!response.ok) {
    const text = await response.text();
    let message = text || "Ошибка API";
    try {
      const data = JSON.parse(text);
      if (data && typeof data.detail === "string") {
        message = data.detail;
      } else if (data && Array.isArray(data.detail)) {
        message = data.detail.map((item) => item.msg || String(item)).join("; ");
      }
    } catch {
      // The body is not JSON — keep the raw text.
    }
    throw new Error(message);
  }
  return response.json();
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 12000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export async function login(username, password) {
  const response = await fetchWithTimeout(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  return parseResponse(response);
}

export async function getRoads(token) {
  const response = await fetchWithTimeout(
    `${API_URL}/roads/geojson`,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
    60000
  );
  return parseResponse(response);
}

export async function getRoadsStatus(token) {
  const response = await fetchWithTimeout(`${API_URL}/roads/status`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse(response);
}

export async function uploadRoads(formData, token) {
  const response = await fetchWithTimeout(
    `${API_URL}/roads/upload`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    },
    120000
  );
  return parseResponse(response);
}

export async function clearRoads(token) {
  const response = await fetchWithTimeout(`${API_URL}/roads`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse(response);
}

export async function getPointRisk(
  token,
  lat,
  lon,
  method = "formula",
  areaHa = 1,
  distances = {}
) {
  const params = new URLSearchParams({
    lat: String(lat),
    lon: String(lon),
    method,
  });
  if (method === "formula") {
    params.set("area_ha", String(areaHa));
    if (distances.roadDistanceM != null) {
      params.set("road_distance_m", String(distances.roadDistanceM));
    }
    if (distances.settlementDistanceM != null) {
      params.set("settlement_distance_m", String(distances.settlementDistanceM));
    }
  }
  const response = await fetchWithTimeout(
    `${API_URL}/risk/point?${params.toString()}`,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
    120000
  );
  return parseResponse(response);
}

export async function getSettlements(token, lat, lon, radiusM = 40000) {
  const params = new URLSearchParams({
    lat: String(lat),
    lon: String(lon),
    radius_m: String(radiusM),
  });
  const response = await fetchWithTimeout(
    `${API_URL}/settlements/geojson?${params.toString()}`,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
    30000
  );
  return parseResponse(response);
}

export async function getOsmRoads(token, lat, lon, radiusM = 5000) {
  const params = new URLSearchParams({
    lat: String(lat),
    lon: String(lon),
    radius_m: String(radiusM),
  });
  const response = await fetchWithTimeout(
    `${API_URL}/roads/osm/geojson?${params.toString()}`,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
    30000
  );
  return parseResponse(response);
}

export async function getFireStatistics(token) {
  const response = await fetchWithTimeout(
    `${API_URL}/stats/fires`,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
    30000
  );
  return parseResponse(response);
}

export async function getFireModelStatus(token) {
  const response = await fetchWithTimeout(`${API_URL}/ai/fire-risk/status`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse(response);
}

export async function preloadFireModel(token) {
  const response = await fetchWithTimeout(`${API_URL}/ai/fire-risk/preload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse(response);
}

export async function classifyFireImage(formData, token) {
  // The first request may load a ~370 MB model on the server.
  const response = await fetchWithTimeout(
    `${API_URL}/ai/fire-risk/image`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    },
    600000
  );
  return parseResponse(response);
}

export async function getUploads(token) {
  const response = await fetchWithTimeout(`${API_URL}/uploads`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse(response);
}

export async function uploadTile(formData, token) {
  // The first request may load the U-Net road model on the server.
  const response = await fetchWithTimeout(
    `${API_URL}/uploads`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    },
    600000
  );
  return parseResponse(response);
}

export async function getAnalyticsSummary(token) {
  const response = await fetchWithTimeout(`${API_URL}/analytics/summary`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse(response);
}

export async function getRiskHistory(token) {
  const response = await fetchWithTimeout(`${API_URL}/risk/history`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse(response);
}

export { API_URL };
