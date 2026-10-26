/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // Empty VITE_API_URL so tests hit the default URL even when frontend/.env sets one.
  test: { environment: 'jsdom', env: { VITE_API_URL: '' } },
})
