async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || JSON.stringify(payload);
    } catch {
      detail = await response.text();
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json();
}

export function getHealth() {
  return request("/api/health");
}

export function createSession() {
  return request("/api/sessions", { method: "POST" });
}

export function getSession(sessionId) {
  return request(`/api/sessions/${sessionId}`);
}

export function setLocation(sessionId, location) {
  return request(`/api/sessions/${sessionId}/location`, {
    method: "POST",
    body: JSON.stringify({ location }),
  });
}

export function sendMessage(sessionId, text) {
  return request(`/api/sessions/${sessionId}/messages`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export function searchProviders(sessionId, category, location) {
  return request(`/api/sessions/${sessionId}/providers/search`, {
    method: "POST",
    body: JSON.stringify({
      category: category || null,
      location: location || null,
    }),
  });
}

export function selectProvider(sessionId, placeId) {
  return request(`/api/sessions/${sessionId}/select`, {
    method: "POST",
    body: JSON.stringify({ place_id: placeId }),
  });
}

export function submitContact(sessionId, contact) {
  return request(`/api/sessions/${sessionId}/contact`, {
    method: "POST",
    body: JSON.stringify(contact),
  });
}
