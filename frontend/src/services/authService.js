import axios from "axios";

const AUTH_URL = "/api/auth/";

export async function getAuthSession() {
  const response = await axios.get(`${AUTH_URL}session/`);
  return response.data;
}

export async function login(credentials) {
  const response = await axios.post(`${AUTH_URL}session/`, credentials);
  return response.data;
}

export async function register(credentials) {
  const response = await axios.post(`${AUTH_URL}register/`, credentials);
  return response.data;
}

export async function logout() {
  const response = await axios.post(`${AUTH_URL}logout/`);
  return response.data;
}
