import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StalenessIndicator } from '../StalenessIndicator';

describe('StalenessIndicator', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('does not display banner when data is fresh', () => {
    const now = Date.now();
    render(<StalenessIndicator lastRefreshedAt={now} />);

    expect(screen.queryByTestId('staleness-banner')).not.toBeInTheDocument();
  });

  it('displays banner when data is stale (after 60 seconds)', () => {
    const sixtyOneSecondsAgo = Date.now() - 61000;
    render(<StalenessIndicator lastRefreshedAt={sixtyOneSecondsAgo} />);

    // Banner should appear immediately since data is already stale
    expect(screen.getByTestId('staleness-banner')).toBeInTheDocument();
    expect(screen.getByText(/Data may be stale/i)).toBeInTheDocument();
  });

  it('displays banner after 60 seconds have passed', async () => {
    const now = Date.now();
    const { rerender } = render(<StalenessIndicator lastRefreshedAt={now} />);

    // Initially not stale
    expect(screen.queryByTestId('staleness-banner')).not.toBeInTheDocument();

    // Advance time by 61 seconds
    await vi.advanceTimersByTimeAsync(61000);

    // Force a re-render to pick up the state change
    rerender(<StalenessIndicator lastRefreshedAt={now} />);

    // Should now be stale
    expect(screen.getByTestId('staleness-banner')).toBeInTheDocument();
  });

  it('respects custom threshold', () => {
    const thirtyOneSecondsAgo = Date.now() - 31000;
    render(<StalenessIndicator lastRefreshedAt={thirtyOneSecondsAgo} threshold={30000} />);

    // Banner should appear immediately since data is stale according to custom threshold
    expect(screen.getByTestId('staleness-banner')).toBeInTheDocument();
  });

  it('displays correct time since refresh', () => {
    const ninetySecondsAgo = Date.now() - 90000;
    render(<StalenessIndicator lastRefreshedAt={ninetySecondsAgo} />);

    expect(screen.getByText(/Last refreshed 90 seconds ago/i)).toBeInTheDocument();
  });

  it('updates display every second', async () => {
    const sixtyOneSecondsAgo = Date.now() - 61000;
    const { rerender } = render(<StalenessIndicator lastRefreshedAt={sixtyOneSecondsAgo} />);

    expect(screen.getByText(/Last refreshed 61 seconds ago/i)).toBeInTheDocument();

    // Advance time by 1 second
    await vi.advanceTimersByTimeAsync(1000);

    // Force a re-render to pick up the state change
    rerender(<StalenessIndicator lastRefreshedAt={sixtyOneSecondsAgo} />);

    expect(screen.getByText(/Last refreshed 62 seconds ago/i)).toBeInTheDocument();
  });
});
