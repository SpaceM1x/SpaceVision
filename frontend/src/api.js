const API_URL =
  import.meta.env.VITE_API_URL || `${window.location.protocol}//${window.location.hostname}:8000`;

async function parseResponse(response) {
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "Ошибка API");
  }
  return response.json();
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 12000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

export async function getUploads(token) {
  const response = await fetchWithTimeout(`${API_URL}/uploads`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse(response);
}

export async function login(username, password) {
  const response = await fetchWithTimeout(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  return parseResponse(response);
}

export async function uploadTile(formData, token) {
  const response = await fetchWithTimeout(`${API_URL}/uploads`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });
  return parseResponse(response);
}

export async function getAnalyticsSummary(token) {
  const response = await fetchWithTimeout(`${API_URL}/analytics/summary`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse(response);
}

export async function getPointRisk(token, lat, lon) {
  const response = await fetchWithTimeout(
    `${API_URL}/risk/point?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
    9000
  );
  return parseResponse(response);
}

export { API_URL };
