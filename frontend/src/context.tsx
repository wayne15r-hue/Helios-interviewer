import { createContext, useContext } from 'react';
import type { Bootstrap, Page } from './types';

export interface AppContextValue {
  data: Bootstrap;
  refresh: () => Promise<void>;
  notify: (message: string, error?: boolean) => void;
  navigate: (page: Page) => void;
  selectedJob: string;
  setSelectedJob: (id: string) => void;
  selectedSession: string;
  setSelectedSession: (id: string) => void;
}
export const AppContext = createContext<AppContextValue | null>(null);
export function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error('Helios app context is missing.');
  return value;
}
export function errorMessage(error: unknown) { return error instanceof Error ? error.message : 'Something went wrong. Please try again.'; }
