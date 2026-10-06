as_num_vec <- function(x) {
  x <- as.numeric(unlist(x))
  x
}

as_int <- function(x, default) {
  v <- suppressWarnings(as.numeric(unlist(x))[1])
  if (is.finite(v)) as.integer(v) else default
}

op_sma <- function(params) {
  x <- as_num_vec(params$values)
  n <- as_int(params$window, 20)
  if (n < 1) stop("window must be >= 1")
  out <- rep(NA_real_, length(x))
  if (length(x) >= n) {
    cs <- cumsum(x)
    out[n:length(x)] <- (cs[n:length(x)] - c(0, cs[1:(length(x) - n)])) / n
  }
  list(values = I(out))
}

op_ema <- function(params) {
  x <- as_num_vec(params$values)
  n <- as_int(params$window, 20)
  if (n < 1) stop("window must be >= 1")
  out <- rep(NA_real_, length(x))
  if (length(x) >= n) {
    out[n] <- mean(x[1:n])
    alpha <- 2 / (n + 1)
    if (length(x) > n) {
      for (i in (n + 1):length(x)) {
        out[i] <- alpha * x[i] + (1 - alpha) * out[i - 1]
      }
    }
  }
  list(values = I(out))
}

op_rsi <- function(params) {
  x <- as_num_vec(params$values)
  n <- as_int(params$window, 14)
  if (n < 1) stop("window must be >= 1")
  out <- rep(NA_real_, length(x))
  if (length(x) > n) {
    delta <- diff(x)
    gains <- pmax(delta, 0)
    losses <- pmax(-delta, 0)
    avg_gain <- mean(gains[1:n])
    avg_loss <- mean(losses[1:n])
    rsi_one <- function(g, l) if (l == 0) 100 else 100 - 100 / (1 + g / l)
    out[n + 1] <- rsi_one(avg_gain, avg_loss)
    if (length(gains) > n) {
      for (i in (n + 1):length(gains)) {
        avg_gain <- (avg_gain * (n - 1) + gains[i]) / n
        avg_loss <- (avg_loss * (n - 1) + losses[i]) / n
        out[i + 1] <- rsi_one(avg_gain, avg_loss)
      }
    }
  }
  list(values = I(out))
}

op_macd <- function(params) {
  x <- as_num_vec(params$values)
  fast <- as_int(params$fast, 12)
  slow <- as_int(params$slow, 26)
  signal_n <- as_int(params$signal, 9)
  if (fast >= slow) stop("fast window must be < slow window")
  ema_fast <- op_ema(list(values = I(x), window = fast))$values
  ema_slow <- op_ema(list(values = I(x), window = slow))$values
  line <- as.numeric(ema_fast - ema_slow)
  signal <- rep(NA_real_, length(line))
  first <- which(is.finite(line))
  if (length(first) >= signal_n) {
    start <- first[1]
    valid <- line[start:length(line)]
    sig <- op_ema(list(values = I(valid), window = signal_n))$values
    signal[start:length(line)] <- sig
  }
  histogram <- line - signal
  list(macd = I(line), signal = I(signal), histogram = I(histogram))
}

op_bollinger <- function(params) {
  x <- as_num_vec(params$values)
  n <- as_int(params$window, 20)
  k <- if (is.null(params$deviations)) 2 else as.numeric(unlist(params$deviations))[1]
  if (n < 2) stop("window must be >= 2")
  lower <- rep(NA_real_, length(x))
  mid <- op_sma(list(values = I(x), window = n))$values
  upper <- lower
  width <- lower
  if (length(x) >= n) {
    for (i in n:length(x)) {
      sd_i <- stats::sd(x[(i - n + 1):i])
      upper[i] <- mid[i] + k * sd_i
      lower[i] <- mid[i] - k * sd_i
      width[i] <- if (mid[i] != 0) (upper[i] - lower[i]) / mid[i] else NA_real_
    }
  }
  list(upper = I(upper), mid = I(mid), lower = I(lower), width = I(width))
}

op_vwap <- function(params) {
  high <- as_num_vec(params$high)
  low <- as_num_vec(params$low)
  close <- as_num_vec(params$close)
  volume <- as_num_vec(params$volume)
  n <- min(length(high), length(low), length(close), length(volume))
  if (n == 0) stop("empty series")
  high <- high[1:n]
  low <- low[1:n]
  close <- close[1:n]
  volume <- volume[1:n]
  typical <- (high + low + close) / 3
  cum_pv <- cumsum(typical * volume)
  cum_vol <- cumsum(volume)
  out <- ifelse(cum_vol > 0, cum_pv / cum_vol, NA_real_)
  list(values = I(as.numeric(out)))
}

op_atr <- function(params) {
  high <- as_num_vec(params$high)
  low <- as_num_vec(params$low)
  close <- as_num_vec(params$close)
  n <- as_int(params$window, 14)
  count <- min(length(high), length(low), length(close))
  if (count < 2) stop("atr requires at least 2 bars")
  high <- high[1:count]
  low <- low[1:count]
  close <- close[1:count]
  prev_close <- c(close[-1], NA)
  tr <- pmax(high - low, abs(high - prev_close), abs(low - prev_close))
  tr[1] <- high[1] - low[1]
  tr[!is.finite(tr)] <- high[!is.finite(tr)] - low[!is.finite(tr)]
  out <- rep(NA_real_, count)
  if (count >= n) {
    out[n] <- mean(tr[1:n])
    if (count > n) {
      for (i in (n + 1):count) {
        out[i] <- (out[i - 1] * (n - 1) + tr[i]) / n
      }
    }
  }
  list(values = I(out))
}
