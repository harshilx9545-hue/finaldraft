import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import { SessionProvider } from '@/session/SessionProvider';
import { ToastProvider } from '@/components/feedback/ToastProvider';
import './styles/index.css';

/**
 * Query defaults chosen against this backend's behaviour:
 *
 * - No global refetch on window focus. `GET /api/invoices` calls
 *   `ensure_period_invoice` server-side, so an incidental refetch can cause the
 *   backend to ISSUE an invoice. Surfaces that genuinely want fresh derived state
 *   opt in per query.
 * - Nothing is retried on a 4xx: that is the server's considered answer.
 * - No structural sharing surprises around 401 — the API client owns refresh and
 *   session teardown, so queries just see a rejected promise.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: false,
      staleTime: 30_000,
      gcTime: 5 * 60_000,
    },
    mutations: { retry: false },
  },
});

const container = document.getElementById('root');
if (container === null) throw new Error('Root element #root is missing from index.html');

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ToastProvider>
          <SessionProvider>
            <App />
          </SessionProvider>
        </ToastProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
