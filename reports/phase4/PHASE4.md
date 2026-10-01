# Phase 4 results (development split)

> Decision-support tool. Not an official warning.

Tune window 2024-04-01..2024-12-31; holdout 2025-01-01..2025-12-31; gate rule: RMSE significantly lower (95 % paired block-bootstrap CI) at >= 3 of 5 lead days and significantly higher at none. Frozen 2026 test data not read.

## rain_pilot · precip

Softmax temperature (tuned on 2024-10-01..2024-12-31): 0.5

|   temperature |   rmse_T_tune |
|--------------:|--------------:|
|         0.500 |        10.930 |
|         1.000 |        10.938 |
|         0.300 |        10.959 |
|         0.200 |        11.005 |
|         0.100 |        11.104 |

**B vs equal_mean** (previous shipped layer): {'candidate': 'blend_B', 'reference': 'equal_mean', 'leads_significantly_better': 3, 'leads_significantly_worse': 0, 'mean_d_rmse': -0.17648544206845324, 'passes': True}

| forecast   |   lead_day |   n_cases |   rmse |   rmse_lo |   rmse_hi |   d_rmse_vs_ref |   d_rmse_lo |   d_rmse_hi |
|:-----------|-----------:|----------:|-------:|----------:|----------:|----------------:|------------:|------------:|
| blend_B    |          1 |     56316 | 10.041 |     8.264 |    11.794 |          -0.270 |      -0.536 |      -0.059 |
| equal_mean |          1 |     56316 | 10.311 |     8.446 |    12.026 |         nan     |     nan     |     nan     |
| blend_B    |          2 |     56472 | 10.161 |     8.383 |    11.871 |          -0.164 |      -0.348 |      -0.011 |
| equal_mean |          2 |     56472 | 10.326 |     8.560 |    12.016 |         nan     |     nan     |     nan     |
| blend_B    |          3 |     56628 | 10.204 |     8.458 |    11.910 |          -0.159 |      -0.341 |      -0.001 |
| equal_mean |          3 |     56628 | 10.364 |     8.654 |    12.120 |         nan     |     nan     |     nan     |
| blend_B    |          4 |     56784 | 10.446 |     8.585 |    12.127 |          -0.147 |      -0.414 |       0.071 |
| equal_mean |          4 |     56784 | 10.592 |     8.756 |    12.271 |         nan     |     nan     |     nan     |
| blend_B    |          5 |     56940 | 10.645 |     8.737 |    12.475 |          -0.142 |      -0.432 |       0.096 |
| equal_mean |          5 |     56940 | 10.787 |     8.897 |    12.509 |         nan     |     nan     |     nan     |

Regime counts ((init, lead) cases):

```
{
 "wet_spell": 1274,
 "dry": 1050,
 "monsoon_normal": 697,
 "monsoon_break": 298,
 "monsoon_active": 225,
 "heavy_rain_risk": 86
}
```

## rain_pilot · tmax

Softmax temperature (tuned on 2024-10-01..2024-12-31): 0.1

|   temperature |   rmse_T_tune |
|--------------:|--------------:|
|         0.100 |         1.141 |
|         0.200 |         1.149 |
|         0.300 |         1.157 |
|         0.500 |         1.166 |
|         1.000 |         1.175 |

**B vs blend_A** (previous shipped layer): {'candidate': 'blend_B', 'reference': 'blend_A', 'leads_significantly_better': 5, 'leads_significantly_worse': 0, 'mean_d_rmse': -0.027060725600179802, 'passes': True}

| forecast   |   lead_day |   n_cases |   rmse |   rmse_lo |   rmse_hi |   d_rmse_vs_ref |   d_rmse_lo |   d_rmse_hi |
|:-----------|-----------:|----------:|-------:|----------:|----------:|----------------:|------------:|------------:|
| blend_A    |          1 |     56316 |  0.964 |     0.920 |     1.012 |         nan     |     nan     |     nan     |
| blend_B    |          1 |     56316 |  0.939 |     0.894 |     0.982 |          -0.025 |      -0.038 |      -0.012 |
| blend_A    |          2 |     56472 |  0.980 |     0.932 |     1.032 |         nan     |     nan     |     nan     |
| blend_B    |          2 |     56472 |  0.954 |     0.904 |     1.003 |          -0.026 |      -0.041 |      -0.010 |
| blend_A    |          3 |     56628 |  1.012 |     0.957 |     1.068 |         nan     |     nan     |     nan     |
| blend_B    |          3 |     56628 |  0.982 |     0.929 |     1.034 |          -0.029 |      -0.046 |      -0.011 |
| blend_A    |          4 |     56784 |  1.030 |     0.971 |     1.089 |         nan     |     nan     |     nan     |
| blend_B    |          4 |     56784 |  1.002 |     0.949 |     1.055 |          -0.028 |      -0.046 |      -0.008 |
| blend_A    |          5 |     56940 |  1.057 |     0.995 |     1.121 |         nan     |     nan     |     nan     |
| blend_B    |          5 |     56940 |  1.030 |     0.971 |     1.093 |          -0.027 |      -0.050 |      -0.002 |

Regime counts ((init, lead) cases):

```
{
 "monsoon_JJAS": 1220,
 "premonsoon_MAM": 920,
 "postmonsoon_OND": 910,
 "winter_JF": 580
}
```

## heat_pilot · precip

Softmax temperature (tuned on 2024-10-01..2024-12-31): 0.1

|   temperature |   rmse_T_tune |
|--------------:|--------------:|
|         0.100 |         2.702 |
|         0.200 |         2.705 |
|         0.300 |         2.716 |
|         0.500 |         2.741 |
|         1.000 |         2.790 |

**B vs equal_mean** (previous shipped layer): {'candidate': 'blend_B', 'reference': 'equal_mean', 'leads_significantly_better': 0, 'leads_significantly_worse': 0, 'mean_d_rmse': 0.10254459727540777, 'passes': False}

| forecast   |   lead_day |   n_cases |   rmse |   rmse_lo |   rmse_hi |   d_rmse_vs_ref |   d_rmse_lo |   d_rmse_hi |
|:-----------|-----------:|----------:|-------:|----------:|----------:|----------------:|------------:|------------:|
| blend_B    |          1 |     61009 |  8.170 |     6.182 |     9.997 |           0.154 |      -0.147 |       0.386 |
| equal_mean |          1 |     61009 |  8.016 |     6.103 |     9.833 |         nan     |     nan     |     nan     |
| blend_B    |          2 |     61178 |  8.549 |     6.447 |    10.632 |           0.020 |      -0.494 |       0.598 |
| equal_mean |          2 |     61178 |  8.529 |     6.430 |    10.344 |         nan     |     nan     |     nan     |
| blend_B    |          3 |     61347 |  8.884 |     6.567 |    11.232 |           0.096 |      -0.379 |       0.598 |
| equal_mean |          3 |     61347 |  8.788 |     6.659 |    10.765 |         nan     |     nan     |     nan     |
| blend_B    |          4 |     61516 |  9.140 |     6.775 |    11.353 |           0.094 |      -0.404 |       0.613 |
| equal_mean |          4 |     61516 |  9.046 |     6.888 |    10.976 |         nan     |     nan     |     nan     |
| blend_B    |          5 |     61685 |  9.360 |     6.789 |    11.823 |           0.149 |      -0.177 |       0.434 |
| equal_mean |          5 |     61685 |  9.210 |     6.830 |    11.484 |         nan     |     nan     |     nan     |

Regime counts ((init, lead) cases):

```
{
 "dry": 1981,
 "monsoon_normal": 554,
 "wet_spell": 427,
 "monsoon_active": 409,
 "monsoon_break": 257,
 "heavy_rain_risk": 2
}
```

## heat_pilot · tmax

Softmax temperature (tuned on 2024-10-01..2024-12-31): 0.3

|   temperature |   rmse_T_tune |
|--------------:|--------------:|
|         0.300 |         0.793 |
|         0.500 |         0.794 |
|         0.200 |         0.794 |
|         0.100 |         0.797 |
|         1.000 |         0.798 |

**B vs blend_A** (previous shipped layer): {'candidate': 'blend_B', 'reference': 'blend_A', 'leads_significantly_better': 0, 'leads_significantly_worse': 3, 'mean_d_rmse': 0.03575875107804727, 'passes': False}

| forecast   |   lead_day |   n_cases |   rmse |   rmse_lo |   rmse_hi |   d_rmse_vs_ref |   d_rmse_lo |   d_rmse_hi |
|:-----------|-----------:|----------:|-------:|----------:|----------:|----------------:|------------:|------------:|
| blend_A    |          1 |     61009 |  0.880 |     0.815 |     0.952 |         nan     |     nan     |     nan     |
| blend_B    |          1 |     61009 |  0.897 |     0.821 |     0.975 |           0.017 |      -0.005 |       0.038 |
| blend_A    |          2 |     61178 |  0.956 |     0.865 |     1.060 |         nan     |     nan     |     nan     |
| blend_B    |          2 |     61178 |  0.973 |     0.874 |     1.082 |           0.017 |      -0.009 |       0.041 |
| blend_A    |          3 |     61347 |  1.031 |     0.921 |     1.144 |         nan     |     nan     |     nan     |
| blend_B    |          3 |     61347 |  1.066 |     0.941 |     1.195 |           0.035 |       0.000 |       0.073 |
| blend_A    |          4 |     61516 |  1.058 |     0.954 |     1.164 |         nan     |     nan     |     nan     |
| blend_B    |          4 |     61516 |  1.114 |     0.981 |     1.247 |           0.056 |       0.015 |       0.098 |
| blend_A    |          5 |     61685 |  1.097 |     0.983 |     1.206 |         nan     |     nan     |     nan     |
| blend_B    |          5 |     61685 |  1.151 |     1.013 |     1.290 |           0.054 |       0.007 |       0.099 |

Regime counts ((init, lead) cases):

```
{
 "monsoon_JJAS": 1204,
 "postmonsoon_OND": 910,
 "premonsoon_MAM": 730,
 "winter_JF": 580,
 "heat": 206
}
```
