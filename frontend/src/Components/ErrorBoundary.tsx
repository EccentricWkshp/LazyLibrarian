// Sonarr's ErrorBoundary: a page that breaks says so, instead of leaving an empty window
import React from 'react';
import { Alert } from './Misc';

interface ErrorBoundaryState {
  error: Error | null;
}

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <Alert kind="danger">
          Something went wrong on this page: {this.state.error.message}. Reload the page to try again.
        </Alert>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
