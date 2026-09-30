/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/renderer/*.html', './src/renderer/src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // 메모라 웹과 같은 이름. 값은 styles.css 의 변수(밝게·어둡게)가 정한다.
      colors: {
        bg: 'var(--bg)',
        fg: 'var(--fg)',
        muted: 'var(--muted)',
        'muted-fg': 'var(--muted-fg)',
        card: 'var(--card)',
        border: 'var(--border)',
        accent: 'var(--accent)',
        'accent-fg': 'var(--accent-fg)',
        'accent-soft': 'var(--accent-soft)',
        danger: 'var(--danger)',
        success: 'var(--success)',
      },
    },
  },
};
