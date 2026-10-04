import axios from 'axios';
const api = axios.create({baseURL: '/api/v1', timeout: 35000});
const auth = token => token ? {Authorization: `Bearer ${token}`} : {};
export const analyzeCode = (payload, token, signal) => api.post('/analyze', payload, {headers: auth(token), signal});
export const analyzeUpload = (file, useMl, token, signal) => {
  const form = new FormData();
  form.append('file', file);
  return api.post(file.name.toLowerCase().endsWith('.zip') ? '/analyze/directory' : '/analyze/file', form,
    {params: {use_ml: useMl}, headers: auth(token), signal});
};
export const searchSimilarTests = (query, token, signal) => api.get('/search_similar', {params: {query}, headers: auth(token), signal});
