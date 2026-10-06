finite_numeric <- function(x) {
  x <- as.numeric(unlist(x))
  x[is.finite(x)]
}

periods_per_year <- function(params) {
  ppy <- suppressWarnings(as.numeric(unlist(params$periods_per_year))[1])
  if (is.finite(ppy) && ppy > 0) ppy else 252
}

span_years <- function(n_prices, params) {
  dates <- params$dates
  if (!is.null(dates) && length(dates) >= 2) {
    d <- as.Date(unlist(dates))
    days <- suppressWarnings(as.numeric(max(d) - min(d)))
    if (is.finite(days) && days > 0) return(days / 365.25)
  }
  ppy <- periods_per_year(params)
  (n_prices - 1) / ppy
}

price_returns <- function(prices) {
  n <- length(prices)
  if (n < 2) stop("need at least 2 prices")
  prices[-1] / prices[-n] - 1
}

equity_from_returns <- function(ret) cumprod(1 + ret)

drawdown_from_equity <- function(equity) equity / cummax(equity) - 1

sharpe_like <- function(mu_ann, sd_ann, rf) {
  if (is.finite(sd_ann) && sd_ann > 0) (mu_ann - rf) / sd_ann else NA_real_
}

risk_stats <- function(ret, ppy, rf, alpha) {
  ret <- ret[is.finite(ret)]
  if (length(ret) < 2) stop("need at least 2 returns")
  mu_ann <- mean(ret) * ppy
  sd_ann <- stats::sd(ret) * sqrt(ppy)
  rf_per <- rf / ppy
  downside <- pmin(ret - rf_per, 0)
  dsd_ann <- sqrt(sum(downside^2) / max(length(ret) - 1, 1)) * sqrt(ppy)
  equity <- cumprod(1 + ret)
  dd <- drawdown_from_equity(equity)
  mdd <- min(dd)
  q <- as.numeric(stats::quantile(ret, probs = alpha, names = FALSE, type = 7))
  tail <- ret[ret <= q]
  cvar <- if (length(tail) > 0) -mean(tail) else NA_real_
  z <- if (stats::sd(ret) > 0) (ret - mean(ret)) / stats::sd(ret) else rep(0, length(ret))
  list(
    observations = length(ret),
    mean_return_annualized = mu_ann,
    volatility = sd_ann,
    sharpe = sharpe_like(mu_ann, sd_ann, rf),
    sortino = if (is.finite(dsd_ann) && dsd_ann > 0) (mu_ann - rf) / dsd_ann else NA_real_,
    max_drawdown = mdd,
    win_rate = mean(ret > 0),
    var = -q,
    cvar = cvar,
    best_period = max(ret),
    worst_period = min(ret),
    skew = mean(z^3),
    kurtosis = mean(z^4)
  )
}

op_performance <- function(params) {
  prices <- finite_numeric(params$prices)
  if (length(prices) < 2) stop("performance requires at least 2 prices")
  ret <- price_returns(prices)
  ppy <- periods_per_year(params)
  rf <- if (is.null(params$risk_free)) 0 else as.numeric(unlist(params$risk_free))[1]
  if (!is.finite(rf)) rf <- 0
  alpha <- if (is.null(params$alpha)) 0.05 else as.numeric(unlist(params$alpha))[1]
  years <- span_years(length(prices), params)
  first <- prices[1]
  last <- prices[length(prices)]
  cagr <- if (first > 0 && years > 0) (last / first)^(1 / years) - 1 else NA_real_
  stats <- risk_stats(ret, ppy, rf, alpha)
  equity <- cumprod(1 + ret)
  mdd <- stats$max_drawdown
  out <- c(
    stats,
    list(
      years = years,
      cagr = cagr,
      total_return = if (first > 0) last / first - 1 else NA_real_,
      calmar = if (is.finite(mdd) && mdd < 0) cagr / abs(mdd) else NA_real_
    )
  )
  out
}

op_drawdown_series <- function(params) {
  prices <- finite_numeric(params$prices)
  if (length(prices) < 2) stop("drawdown_series requires at least 2 prices")
  equity <- cumprod(c(1, 1 + price_returns(prices)))
  dd <- drawdown_from_equity(equity)
  list(values = I(as.numeric(dd)))
}

op_equity_curve <- function(params) {
  prices <- finite_numeric(params$prices)
  if (length(prices) < 2) stop("equity_curve requires at least 2 prices")
  values <- cumprod(1 + price_returns(prices))
  list(values = I(c(1, as.numeric(values))))
}

op_xirr <- function(params) {
  dates <- as.Date(unlist(params$dates))
  amounts <- as.numeric(unlist(params$amounts))
  if (length(dates) != length(amounts)) stop("dates and amounts must have equal length")
  if (length(dates) < 2) stop("xirr requires at least 2 cash flows")
  ord <- order(dates)
  dates <- dates[ord]
  amounts <- amounts[ord]
  if (!any(amounts > 0) || !any(amounts < 0)) stop("xirr requires both inflows and outflows")
  t <- as.numeric(dates - dates[1]) / 365.25
  npv <- function(r) sum(amounts / (1 + r)^t)
  lo <- -0.999999
  hi <- 10
  f_lo <- npv(lo)
  f_hi <- npv(hi)
  if (!is.finite(f_lo) || !is.finite(f_hi) || f_lo * f_hi > 0) stop("could not bracket xirr root")
  mid <- (lo + hi) / 2
  for (i in seq_len(200)) {
    mid <- (lo + hi) / 2
    f_mid <- npv(mid)
    if (!is.finite(f_mid)) break
    if (abs(f_mid) < 1e-11) return(mid)
    if (f_lo * f_mid < 0) {
      hi <- mid
      f_hi <- f_mid
    } else {
      lo <- mid
      f_lo <- f_mid
    }
  }
  (lo + hi) / 2
}
