import type { Bridge } from '@shared/contract';

declare global {
  interface Window {
    memora: Bridge;
  }
}

export const api = (): Bridge => window.memora;
export {};
