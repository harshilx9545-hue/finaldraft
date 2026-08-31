import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'coverage'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.es2022 },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // The design system is the only place values live. A raw hex in a component
      // means a token was bypassed.
      'no-restricted-syntax': [
        'error',
        {
          selector: "Literal[value=/^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/]",
          message:
            'No hex colours in source. Add a token in styles/tokens.css and use the Tailwind theme key.',
        },
      ],
    },
  },
  {
    // Token and theme files are where literal values belong. Tests assert on real
    // backend strings, including hex-shaped ones.
    files: ['tailwind.config.ts', '**/*.test.{ts,tsx}', 'src/test/**'],
    rules: { 'no-restricted-syntax': 'off' },
  },
  {
    // Context providers export their consumer hook alongside the component. That is
    // the idiomatic React pattern and keeps the context object private to the
    // module. The cost is Fast Refresh for these two files only, which are
    // infrastructure and rarely edited during UI work — a worse trade than the
    // indirection of a separate hook file per provider.
    files: ['src/session/SessionProvider.tsx', 'src/components/feedback/ToastProvider.tsx'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
);
