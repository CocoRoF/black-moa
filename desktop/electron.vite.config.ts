import { resolve } from 'node:path';
import { defineConfig, externalizeDepsPlugin } from 'electron-vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: { rollupOptions: { input: { index: resolve('src/main/index.ts') } } },
    resolve: { alias: { '@shared': resolve('src/shared') } },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: { rollupOptions: { input: { index: resolve('src/preload/index.ts'), host: resolve('src/preload/host.ts') } } },
    resolve: { alias: { '@shared': resolve('src/shared') } },
  },
  renderer: {
    root: 'src/renderer',
    plugins: [react()],
    build: {
      // 앱이 직접 그리는 화면: 본창의 틀(아이콘 막대·제목 줄·알림·설정), 아바타와 그 컨트롤, 빠른 대화.
      // 세 문의 안쪽은 memo-ora.com 이 그린다(plan/62).
      rollupOptions: {
        input: {
          shell: resolve('src/renderer/shell.html'),
          avatar: resolve('src/renderer/avatar.html'),
          chip: resolve('src/renderer/chip.html'),
          quick: resolve('src/renderer/quick.html'),
        },
      },
    },
    resolve: { alias: { '@': resolve('src/renderer/src'), '@shared': resolve('src/shared') } },
  },
});
