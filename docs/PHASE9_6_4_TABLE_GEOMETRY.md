# Phase 9.6.4 — Table Geometry

## Algorithm

1. Drop body columns that are empty or symbol-only (`$`, `%`, dashes).
2. Collect printed periods left-to-right from all header rows.
3. For each body row, collect the columns that actually hold a number.
4. Assign periods in printed order only when the row's numeric count equals the printed period
   count. Otherwise the row keeps column-header ancestry and, if that does not identify a single
   period, its period stays unresolved.

## Coca-Cola FY2022 trace

`TAB-156608b48f668e96` prints `2022 | 2021 | 2020`; the revenue row contains `$ 43,004 $ 38,655 $
33,014` because the currency symbol occupies its own cells. A 43,004/38,655/33,014 trace assigns
2022/2021/2020 respectively, matching the printed order and the statement's own arithmetic
(43,004 − 18,000 = 25,004 gross profit). No right-alignment to an expected year is performed.

## Conservative cases

- A two-value row in a three-period table is left unresolved rather than assigned the newest
  period (`test_row_with_two_values_in_three_period_table_leaves_period_unresolved`).
- Currency columns present only on some rows do not shift periods
  (`test_currency_columns_present_on_some_rows_do_not_shift_periods`, assets 92,763/94,354).
- A single printed period is still assigned; this was the root cause of the 9.6.3 regression
  (`test_conflicting_row_labels_are_ambiguous` expected period 2020).

## Limits

The corpus stores flattened row arrays without colspan/rowspan metadata, so a row that both omits
a column and keeps the period count is not detectable from structure alone; such cells remain
marked unresolved only when counts disagree.
