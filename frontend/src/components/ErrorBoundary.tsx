import { Component, type ReactNode } from "react";

interface State {
  error: Error | null;
}

/** Keeps one broken view from blanking the app; the rest of the shell stays usable. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  componentDidCatch(error: Error) {
    console.error("view crashed", error);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="m-4 rounded-lg border border-line bg-surface p-6 text-center">
        <p className="text-sm font-medium text-fg">This view hit an unexpected problem.</p>
        <p className="mt-1 text-xs text-muted">Other pages still work. Reloading usually fixes it.</p>
        <div className="mt-3 flex justify-center gap-2">
          <button
            onClick={() => this.setState({ error: null })}
            className="rounded-md border border-line px-3 py-1 text-xs text-muted hover:text-fg"
          >
            Try again
          </button>
          <button
            onClick={() => window.location.reload()}
            className="rounded-md bg-accent px-3 py-1 text-xs font-medium text-white"
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}
