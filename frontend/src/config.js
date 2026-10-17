// Single source of truth for app-level constants. The app name is never
// hardcoded in copy — components and strings reference APP_NAME.
export const APP_NAME = "Sushruta";

// Persistent emergency number. Default 112 (common EU/India emergency line).
// A real deployment would make this configurable per region.
export const EMERGENCY_NUMBER = "112";

// Which wound the dashboard is currently showing. A real app would route this.
export const DEFAULT_WOUND_ID = "A-204";

// Base path for the backend API. In dev, vite proxies "/api" -> FastAPI.
export const API_BASE = "/api";
