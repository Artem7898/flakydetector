import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' }
});

export const analyzeCode = (payload) => api.post('/analyze', payload);
export const getPatternCatalog = () => api.get('/patterns/catalog');