Fixed
Trust evidence now names the actual reason a gain is refused as noise: too few
baseline repeats to bound a floor, a gain inside the floor (printed as a band
around the baseline mean rather than an absolute interval against a delta), or
a gain below `min_effect`. `gain_over_noise` is `0.0` when the floor is
undefined instead of a ratio over an epsilon (#1089).
