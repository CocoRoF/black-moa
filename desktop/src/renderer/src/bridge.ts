import type { Bridge } from '@shared/contract';

declare global {
  interface Window {
    blackmoa: Bridge;
  }
}

export const api = (): Bridge => window.blackmoa;
export {};
