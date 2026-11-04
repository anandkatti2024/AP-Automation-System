import { AlertCircle } from "lucide-react";

function MessageBanner({ message, variant = "info", onDismiss }) {
  if (!message) return null;

  const className =
    variant === "error" ? "message-banner error-banner" : "message-banner";

  return (
    <div className={className}>
      <AlertCircle size={18} /> {message}
      {onDismiss && (
        <button onClick={onDismiss} aria-label="Dismiss message">
          ×
        </button>
      )}
    </div>
  );
}

export default MessageBanner;
