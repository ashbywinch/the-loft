import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'happy-dom',
    include: ['app/tests/**/*.test.js'],
    coverage: {
      provider: 'istanbul',
      reporters: ['text', 'clover'],
      reportsDirectory: 'app/coverage',
      include: ['app/**/*.js'],
      exclude: ['app/tests/**'],
    },
  },
});
