import React from 'react';
import { AlertTriangle, X } from 'lucide-react';

interface ErrorBannerProps {
  message: string;
  onDismiss: () => void;
}

export const ErrorBanner: React.FC<ErrorBannerProps> = ({ message, onDismiss }) => {
  return (
    <div
      role="alert"
      className="glass flex items-start gap-3 rounded-2xl border-red-500/30 p-3 text-sm"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
      <p className="flex-1 text-white/90">{message}</p>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={onDismiss}
        className="rounded-full p-1 text-white/50 hover:bg-white/5 hover:text-white"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
};
