import { normalizeEmailInput } from './settingsModel';

export const USER_EMAIL_STORAGE_KEY = 'stock-opportunity-lab:user-email';

export function readStoredUserEmail(): string {
  if (typeof window === 'undefined') {
    return '';
  }
  return normalizeEmailInput(window.localStorage.getItem(USER_EMAIL_STORAGE_KEY) ?? '');
}

export function writeStoredUserEmail(value: string): string {
  const email = normalizeEmailInput(value);
  if (email) {
    window.localStorage.setItem(USER_EMAIL_STORAGE_KEY, email);
  } else {
    window.localStorage.removeItem(USER_EMAIL_STORAGE_KEY);
  }
  window.dispatchEvent(new CustomEvent(USER_EMAIL_STORAGE_KEY));
  return email;
}

export function subscribeStoredUserEmail(listener: (email: string) => void): () => void {
  const handleStorage = (event: StorageEvent) => {
    if (event.key === USER_EMAIL_STORAGE_KEY) {
      listener(readStoredUserEmail());
    }
  };
  const handleLocalChange = () => listener(readStoredUserEmail());
  window.addEventListener('storage', handleStorage);
  window.addEventListener(USER_EMAIL_STORAGE_KEY, handleLocalChange);
  return () => {
    window.removeEventListener('storage', handleStorage);
    window.removeEventListener(USER_EMAIL_STORAGE_KEY, handleLocalChange);
  };
}
