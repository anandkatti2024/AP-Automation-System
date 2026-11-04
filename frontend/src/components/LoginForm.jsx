import { useState } from "react";
import { LockKeyhole, UserPlus } from "lucide-react";

function LoginForm({ onLogin, onRegister, loading, error }) {
  const [isRegistering, setIsRegistering] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    if (isRegistering) {
      if (password !== confirmPassword) {
        return;
      }
      await onRegister({ username: username.trim(), password });
      return;
    }
    await onLogin({ username: username.trim(), password });
  }

  return (
    <main className="login-page">
      <section className="login-card">
        <div className="brand-mark">T</div>
        <div className="eyebrow">TEMPLEGATE AP AUTOMATION</div>
        <h1>{isRegistering ? "Create your account" : "Sign in"}</h1>
        <p>
          {isRegistering
            ? "Create an AP Clerk account to get started."
            : "Use your AP workspace account to continue."}
        </p>
        {error && <div className="vendor-error" role="alert">{error}</div>}
        <form onSubmit={handleSubmit}>
          <label className="review-field">
            <span>Username</span>
            <input
              autoComplete="username"
              name="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
          </label>
          <label className="review-field">
            <span>Password</span>
            <input
              type="password"
              autoComplete={isRegistering ? "new-password" : "current-password"}
              name="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {isRegistering && (
            <label className="review-field">
              <span>Confirm password</span>
              <input
                type="password"
                autoComplete="new-password"
                name="confirm-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                required
              />
              {password !== confirmPassword && confirmPassword && (
                <small className="field-error" role="alert">
                  Passwords do not match.
                </small>
              )}
            </label>
          )}
          <button
            className="button primary"
            type="submit"
            disabled={loading || (isRegistering && password !== confirmPassword)}
          >
            {isRegistering ? <UserPlus size={16} /> : <LockKeyhole size={16} />}
            {loading
              ? isRegistering ? "Creating account..." : "Signing in..."
              : isRegistering ? "Create account" : "Sign in"}
          </button>
        </form>
        <small>
          {isRegistering
            ? "New accounts start with AP Clerk access. An administrator assigns other roles."
            : "Accounts and roles are managed by your administrator."}
        </small>
        <button
          className="auth-mode-toggle"
          type="button"
          onClick={() => {
            setIsRegistering((current) => !current);
            setConfirmPassword("");
          }}
          disabled={loading}
        >
          {isRegistering
            ? "Already have an account? Sign in"
            : "New to Templegate? Create an account"}
        </button>
      </section>
    </main>
  );
}

export default LoginForm;
