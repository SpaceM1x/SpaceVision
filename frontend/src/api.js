const API_URL = "http://127.0.0.1:8000";

async function parseResponse(response) {
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "Ошибка API");
  }
  return response.json();
}

export async function getUploads(token) {
  const response = await fetch(`${API_URL}/uploads`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse(response);
}

export async function login(username, password) {
  const response = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  return parseResponse(response);
}

export async function uploadTile(formData, token) {
  const response = await fetch(`${API_URL}/uploads`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });
  return parseResponse(response);
}

export { API_URL };
