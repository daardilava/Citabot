// Thin client for the JSON API. Every view talks to the server through here.

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "No hay conexión con el servidor. ¿Sigue corriendo?");
  }
  const data = await response.json().catch(() => null);
  if (response.status === 401 && !path.startsWith("/api/auth/") && location.pathname !== "/login") {
    location.assign("/login"); // the session ended: back to the sign-in page
  }
  if (!response.ok) {
    const error = data?.error ?? {};
    throw new ApiError(response.status, error.code ?? "error", error.message ?? "Algo salió mal.");
  }
  return data;
}

const query = (params) => new URLSearchParams(params).toString();

export const api = {
  health: () => request("GET", "/api/health"),
  me: () => request("GET", "/api/auth/me"),
  signup: (account) => request("POST", "/api/auth/signup", account),
  login: (credentials) => request("POST", "/api/auth/login", credentials),
  loginDemo: () => request("POST", "/api/auth/demo", {}),
  logout: () => request("POST", "/api/auth/logout", {}),

  dashboard: () => request("GET", "/api/dashboard"),
  resetDemo: () => request("POST", "/api/demo/reset"),

  business: () => request("GET", "/api/business"),
  updateBusiness: (business) => request("PUT", "/api/business", business),
  services: () => request("GET", "/api/services"),
  addService: (service) => request("POST", "/api/services", service),
  updateService: (id, service) => request("PUT", `/api/services/${id}`, service),
  deleteService: (id) => request("DELETE", `/api/services/${id}`),

  conversations: () => request("GET", "/api/conversations"),
  conversation: (id) => request("GET", `/api/conversations/${id}`),
  updateConversation: (id, changes) => request("PATCH", `/api/conversations/${id}`, changes),
  reply: (id, text) => request("POST", `/api/conversations/${id}/messages`, { text }),

  appointments: (from, to) => request("GET", `/api/appointments?${query({ from, to })}`),
  createAppointment: (appointment) => request("POST", "/api/appointments", appointment),
  setAppointmentStatus: (id, status) => request("PATCH", `/api/appointments/${id}`, { status }),
  availability: (serviceId, date) =>
    request("GET", `/api/availability?${query({ service_id: serviceId, date })}`),
  runReminders: () => request("POST", "/api/reminders/run"),

  docs: () => request("GET", "/api/knowledge"),
  addDoc: (doc) => request("POST", "/api/knowledge", doc),
  deleteDoc: (id) => request("DELETE", `/api/knowledge/${id}`),
  searchDocs: (text) => request("POST", "/api/knowledge/search", { query: text }),

  simulate: (message) => request("POST", "/api/simulator/messages", message),
};
