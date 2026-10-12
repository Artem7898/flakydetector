import axios from 'axios';
import {sourceUploadEndpoint} from './uploads.js';
const api = axios.create({baseURL: '/api/v1', timeout: 35000});
const auth = token => token ? {Authorization: `Bearer ${token}`} : {};
export const analyzeCode = (payload, token, signal, options = {}) => api.post('/analyze', payload, {params: options, headers: auth(token), signal});
export const analyzeUpload = (file, useMl, token, signal, options = {}) => {
  const endpoint = sourceUploadEndpoint(file);
  const form = new FormData(); form.append('file', file);
  return api.post(endpoint, form,
    {params: {use_ml: useMl, ...options}, headers: auth(token), signal});
};
export const searchSimilarTests = (query, token, signal) => api.get('/search_similar', {params: {query}, headers: auth(token), signal});
export const exportAnalysis = (analysis, token, format, includeSource = false) => api.post('/export',
  {analysis, format, include_source: includeSource, confirm_source: includeSource}, {params: {workspace: analysis.workspace}, headers: auth(token)});
export const runtimeGet = (path, repo, workspace, token, signal) => api.get(path, {params: {repo, workspace}, headers: auth(token), signal});
export const runtimePost = (path, payload, workspace, token, signal) => api.post(path, payload, {params: {workspace}, headers: auth(token), signal});
