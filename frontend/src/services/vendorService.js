import axios from "axios";

const API_URL = "/api/invoices/vendors/";

export async function getVendors() {
  const response = await axios.get(API_URL);
  const data = response.data;
  return Array.isArray(data) ? data : data.results || [];
}

export async function createVendor(vendor) {
  const response = await axios.post(API_URL, vendor);
  return response.data;
}

export async function updateVendor(vendorId, vendor) {
  const response = await axios.patch(`${API_URL}${vendorId}/`, vendor);
  return response.data;
}

export async function submitVendorForReview(vendorId, comment = "") {
  const response = await axios.post(
    `${API_URL}${vendorId}/submit-for-review/`,
    { comment }
  );
  return response.data;
}

export async function approveVendor(vendorId, comment = "") {
  const response = await axios.post(`${API_URL}${vendorId}/approve/`, {
    comment,
  });
  return response.data;
}

export async function rejectVendor(vendorId, comment) {
  const response = await axios.post(`${API_URL}${vendorId}/reject/`, {
    comment,
  });
  return response.data;
}
