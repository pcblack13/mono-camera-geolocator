/**
 * `common/ErrorBoundary.tsx` — 50-frontend §2.26.
 *
 * ★ Instantiated at THREE levels: root, per-pane, per-panel. "A Konva crash must not
 *   take out the map, and vice versa." A React render error is contained at the
 *   nearest boundary, so one subsystem failing leaves the rest of the workspace
 *   usable — which for a field surveyor mid-survey is the difference between "the map
 *   pane is broken, keep working" and a white screen.
 *
 * ★ `resetKeys` lets a boundary recover WITHOUT a full reload: when any key changes
 *   (typically the imageId or a retry counter) the boundary clears its error and
 *   re-renders its children. This is how "switch to another image" recovers a pane
 *   that threw on the previous one.
 *
 * ★ A class component, necessarily — `getDerivedStateFromError`/`componentDidCatch`
 *   have no hook equivalent.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';

export interface ErrorBoundaryProps {
  children: ReactNode;
  /**
   * Rendered when a child throws. Either a static node or a render function that
   * receives the error and a `reset` callback so the fallback can offer "Try again".
   */
  fallback: ReactNode | ((error: Error, reset: () => void) => ReactNode);
  /** Side-effect hook — log/report. NEVER swallow: this is the reporting seam. */
  onError?: (error: Error, info: ErrorInfo) => void;
  /**
   * When any value in this array changes between renders, the boundary resets. Use
   * the identity of what the subtree renders (e.g. `[imageId]`) so navigating away
   * from the thing that crashed clears the error automatically.
   */
  resetKeys?: readonly unknown[];
}

interface ErrorBoundaryState {
  error: Error | null;
}

function keysChanged(
  a: readonly unknown[] | undefined,
  b: readonly unknown[] | undefined,
): boolean {
  if (a === b) return false;
  if (!a || !b || a.length !== b.length) return true;
  for (let i = 0; i < a.length; i += 1) {
    if (!Object.is(a[i], b[i])) return true;
  }
  return false;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { error: null };
    this.reset = this.reset.bind(this);
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    this.props.onError?.(error, info);
  }

  override componentDidUpdate(prev: ErrorBoundaryProps): void {
    // ★ Only auto-reset when we ARE showing an error AND the keys moved — otherwise a
    //   parent re-render with new keys would clear an error the user hasn't seen.
    if (this.state.error !== null && keysChanged(prev.resetKeys, this.props.resetKeys)) {
      this.reset();
    }
  }

  reset(): void {
    this.setState({ error: null });
  }

  override render(): ReactNode {
    const { error } = this.state;
    const { fallback, children } = this.props;

    if (error !== null) {
      return typeof fallback === 'function' ? fallback(error, this.reset) : fallback;
    }
    return children;
  }
}

export default ErrorBoundary;
