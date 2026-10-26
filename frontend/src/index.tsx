import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from 'App/App';
import 'Styles/globals.css';

document.documentElement.dataset.theme = window.LazyLibrarian?.theme ?? 'dark';

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>
);
