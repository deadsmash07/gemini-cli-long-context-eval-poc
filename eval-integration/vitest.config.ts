import {defineConfig} from 'vitest/config';

export default defineConfig({
  test: {
    testTimeout: 900000, // 15 minutes -- coding tasks need more time
    reporters: ['default', 'json'],
    outputFile: {
      json: 'logs/report.json',
    },
    include: ['**/*.eval.ts'],
    environment: 'node',
    globals: true,
  },
});
