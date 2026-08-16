import js from '@eslint/js';
import globals from 'globals';
import prettier from 'eslint-config-prettier';

export default [
  { ignores: ['node_modules/**', 'app/coverage/**', 'app/vendor/**'] },
  js.configs.recommended,
  {
    files: ['app/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser, L: 'readonly', OpenSeadragon: 'readonly' },
    },
  },
  // the vitest tests run under node (readFileSync, process.cwd) — the app
  // code itself stays browser-globals-only
  {
    files: ['app/**/*.test.js', 'app/tests/**/*.js'],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
  prettier, // last: disables style rules prettier owns
];
