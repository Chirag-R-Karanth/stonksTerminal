named_weights <- function(symbols, weights) {
  out <- as.list(round(weights, 6))
  names(out) <- symbols
  out
}

op_portfolio_stats <- function(params) {
  symbols <- as.character(unlist(params$symbols))
  weights <- as.numeric(unlist(params$weights))
  if (length(symbols) != length(weights)) stop("symbols and weights length mismatch")
  if (!length(symbols)) stop("empty portfolio")
  ret_list <- params$returns
  columns <- lapply(symbols, function(s) {
    as.numeric(unlist(ret_list[[s]]))
  })
  n <- min(vapply(columns, length, integer(1)))
  if (n < 2) stop("insufficient overlapping return observations")
  R <- do.call(cbind, lapply(columns, function(v) v[seq_len(n)]))
  colnames(R) <- symbols
  complete <- stats::complete.cases(R)
  R <- R[complete, , drop = FALSE]
  if (nrow(R) < 2) stop("insufficient overlapping return observations")

  ppy <- periods_per_year(params)
  rf <- if (is.null(params$risk_free)) 0 else as.numeric(unlist(params$risk_free))[1]
  if (!is.finite(rf)) rf <- 0
  alpha_q <- if (is.null(params$alpha)) 0.05 else as.numeric(unlist(params$alpha))[1]

  total_w <- sum(weights)
  if (total_w <= 0) stop("weights must sum to a positive number")
  w <- weights / total_w

  port_r <- as.numeric(R %*% w)
  stats <- risk_stats(port_r, ppy, rf, alpha_q)

  cov_ann <- stats::cov(R) * ppy
  w_col <- matrix(w, ncol = 1)
  port_vol_weights <- as.numeric(sqrt(t(w_col) %*% cov_ann %*% w_col))
  marginal <- as.numeric(cov_ann %*% w_col)
  contrib <- w * marginal
  contrib_pct <- if (port_vol_weights > 0) contrib / port_vol_weights else rep(NA_real_, length(w))

  hhi <- sum(w^2)
  max_weight <- max(w)

  bench_stats <- NULL
  if (!is.null(params$bench_returns)) {
    bench_vec <- as.numeric(unlist(params$bench_returns))
    m <- min(length(bench_vec), length(port_r))
    rp <- port_r[seq_len(m)]
    rb <- bench_vec[seq_len(m)]
    keep <- is.finite(rp) & is.finite(rb)
    rp <- rp[keep]
    rb <- rb[keep]
    if (length(rp) >= 2) {
      if (stats::var(rb) <= 0) stop("benchmark returns have zero variance")
      beta <- stats::cov(rp, rb) / stats::var(rb)
      alpha_ann <- (mean(rp) - beta * mean(rb)) * ppy
      te <- stats::sd(rp - rb) * sqrt(ppy)
      corr <- stats::cor(rp, rb)
      bench_stats <- list(
        beta = beta,
        alpha_annualized = alpha_ann,
        tracking_error = te,
        information_ratio = if (te > 0) (mean(rp - rb) * ppy) / te else NA_real_,
        correlation = corr,
        benchmark_return_annualized = mean(rb) * ppy,
        excess_return_annualized = (mean(rp) - mean(rb)) * ppy
      )
    }
  }

  corr_mat <- stats::cor(R)
  corr_rows <- unname(split(round(as.numeric(t(corr_mat)), 4), row(corr_mat)))

  out <- c(
    stats,
    list(
      symbols = I(symbols),
      weights = named_weights(symbols, w),
      volatility_from_weights = port_vol_weights,
      risk_contributions = named_weights(symbols, contrib_pct),
      concentration_hhi = hhi,
      effective_positions = if (hhi > 0) 1 / hhi else NA_real_,
      max_weight = max_weight,
      correlation_matrix = corr_rows,
      benchmark = bench_stats
    )
  )
  out
}

op_beta_alpha <- function(params) {
  port <- as.numeric(unlist(params$returns))
  bench <- as.numeric(unlist(params$bench_returns))
  ppy <- periods_per_year(params)
  m <- min(length(port), length(bench))
  if (m < 2) stop("need at least 2 aligned observations")
  rp <- port[1:m]
  rb <- bench[1:m]
  keep <- is.finite(rp) & is.finite(rb)
  rp <- rp[keep]
  rb <- rb[keep]
  if (length(rp) < 2) stop("no finite overlapping observations")
  if (stats::var(rb) == 0) stop("benchmark has zero variance")
  beta <- stats::cov(rp, rb) / stats::var(rb)
  alpha_ann <- (mean(rp) - beta * mean(rb)) * ppy
  te <- stats::sd(rp - rb) * sqrt(ppy)
  list(
    n = length(rp),
    beta = beta,
    alpha_annualized = alpha_ann,
    tracking_error = te,
    information_ratio = if (te > 0) (mean(rp - rb) * ppy) / te else NA_real_,
    correlation = stats::cor(rp, rb),
    r_squared = stats::cor(rp, rb)^2
  )
}

op_correlation <- function(params) {
  symbols <- as.character(unlist(params$symbols))
  ret_list <- params$returns
  columns <- lapply(symbols, function(s) as.numeric(unlist(ret_list[[s]])))
  n <- min(vapply(columns, length, integer(1)))
  if (n < 2) stop("need at least 2 observations")
  R <- do.call(cbind, lapply(columns, function(v) v[seq_len(n)]))
  colnames(R) <- symbols
  R <- R[stats::complete.cases(R), , drop = FALSE]
  if (nrow(R) < 2) stop("insufficient complete observations")
  corr <- stats::cor(R)
  list(
    symbols = I(symbols),
    matrix = unname(split(round(as.numeric(t(corr)), 4), row(corr))),
    n = nrow(R)
  )
}

op_regression <- function(params) {
  y <- as.numeric(unlist(params$y))
  x_list <- params$x
  if (is.null(x_list) || !length(x_list)) stop("at least one independent variable required")
  n <- length(y)
  x_names <- names(x_list)
  if (is.null(x_names)) x_names <- paste0("x", seq_along(x_list))
  frame <- data.frame(y = y)
  for (i in seq_along(x_list)) {
    frame[[x_names[i]]] <- as.numeric(unlist(x_list[[i]]))
  }
  frame <- frame[stats::complete.cases(frame), , drop = FALSE]
  if (nrow(frame) < 3) stop("need at least 3 complete observations")
  fit <- stats::lm(y ~ ., data = frame)
  s <- summary(fit)
  coefs <- s$coefficients
  list(
    n = nrow(frame),
    r_squared = unname(s$r.squared),
    adj_r_squared = unname(s$adj.r.squared),
    residual_std_error = unname(s$sigma),
    coefficients = lapply(seq_len(nrow(coefs)), function(i) {
      list(term = rownames(coefs)[i], estimate = coefs[i, 1], std_error = coefs[i, 2],
           t_value = coefs[i, 3], p_value = coefs[i, 4])
    })
  )
}
