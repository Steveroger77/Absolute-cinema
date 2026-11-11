"""Temporal per-user train/validation/test splitting with strict zero-leakage guarantees."""

from __future__ import annotations

import pandas as pd


def temporal_user_split(
    ratings_df: pd.DataFrame,
    test_ratio: float = 0.20,
    val_ratio: float = 0.10,
    min_user_ratings: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Split ratings per user strictly by timestamp without leakage.

    For users with >= min_user_ratings:
      - Last `test_ratio` (20%) chronologically -> test_df
      - Prior `val_ratio` (10% of total) -> val_df
      - Earliest remainder -> train_df
    Users with < min_user_ratings stay in train_df only.
    """
    df = ratings_df.sort_values(["user_id", "timestamp", "movie_id"]).reset_index(drop=True)
    train_parts: list[pd.DataFrame] = []
    val_parts: list[pd.DataFrame] = []
    test_parts: list[pd.DataFrame] = []

    for _, group in df.groupby("user_id", sort=False):
        n = len(group)
        if n < min_user_ratings:
            train_parts.append(group)
            continue
        n_test = max(1, int(n * test_ratio))
        n_val = max(1, int(n * val_ratio)) if (n - n_test) >= 4 else 0
        split_val = n - n_test - n_val
        split_test = n - n_test
        train_parts.append(group.iloc[:split_val])
        if n_val > 0:
            val_parts.append(group.iloc[split_val:split_test])
        test_parts.append(group.iloc[split_test:])

    train_df = pd.concat(train_parts, ignore_index=True) if train_parts else df.iloc[:0].copy()
    val_df = pd.concat(val_parts, ignore_index=True) if val_parts else df.iloc[:0].copy()
    test_df = pd.concat(test_parts, ignore_index=True) if test_parts else df.iloc[:0].copy()
    assert_no_leakage(train_df, test_df)
    if not val_df.empty:
        assert_no_leakage(train_df, val_df)
    return train_df, val_df, test_df


def assert_no_leakage(train_df: pd.DataFrame, holdout_df: pd.DataFrame) -> None:
    """Raise AssertionError if any holdout (user, movie) or chronological violation leaks into train."""
    if holdout_df.empty or train_df.empty:
        return
    train_pairs = set(zip(train_df["user_id"].astype(int), train_df["movie_id"].astype(int), strict=False))
    hold_pairs = set(zip(holdout_df["user_id"].astype(int), holdout_df["movie_id"].astype(int), strict=False))
    overlap = train_pairs.intersection(hold_pairs)
    assert not overlap, f"Data leakage detected: {len(overlap)} interactions in both train and holdout"

    train_max = train_df.groupby("user_id")["timestamp"].max()
    hold_min = holdout_df.groupby("user_id")["timestamp"].min()
    common = train_max.index.intersection(hold_min.index)
    violating = common[train_max.loc[common] > hold_min.loc[common]]
    assert len(violating) == 0, f"Temporal leakage detected for {len(violating)} users"
