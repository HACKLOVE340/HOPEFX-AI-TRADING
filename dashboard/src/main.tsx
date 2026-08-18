import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      refetchInterval: 10000,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* Served under /godmode/ (see vite.config.ts `base` and the mount in
          core/page_routes.py). Without a basename every route below — declared
          as "/", "/checkout", "/dashboard" — is matched against the full
          "/godmode/..." pathname and nothing matches, so the shell renders
          empty. BASE_URL comes from the same `base`, keeping the two in step. */}
      <BrowserRouter basename={import.meta.env.BASE_URL}>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
