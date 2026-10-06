options(warn = 1)

args <- commandArgs(trailingOnly = FALSE)
file_arg <- sub("^--file=", "", grep("^--file=", args, value = TRUE))
script_dir <- if (length(file_arg)) dirname(normalizePath(file_arg)) else getwd()

lib_env <- Sys.getenv("FT_R_LIBS", unset = "")
if (nzchar(lib_env)) .libPaths(c(path.expand(lib_env), .libPaths()))
default_lib <- path.expand("~/.local/share/R/library")
if (dir.exists(default_lib)) .libPaths(c(default_lib, .libPaths()))

suppressPackageStartupMessages(library(jsonlite))

source(file.path(script_dir, "metrics.R"))
source(file.path(script_dir, "indicators.R"))
source(file.path(script_dir, "valuation.R"))
source(file.path(script_dir, "portfolio.R"))

`%||%` <- function(a, b) {
  if (is.null(a) || length(a) == 0) return(b)
  a
}

sanitize <- function(x) {
  if (is.list(x) && !is.data.frame(x)) return(lapply(x, sanitize))
  if (is.data.frame(x)) return(lapply(x, sanitize))
  if (is.numeric(x)) {
    x[!is.finite(x)] <- NA
    return(x)
  }
  x
}

dispatch <- function(op, params) {
  if (is.null(params)) params <- list()
  switch(
    op,
    ping = list(status = "ok", version = as.character(getRversion())),
    performance = op_performance(params),
    xirr = op_xirr(params),
    drawdown_series = op_drawdown_series(params),
    equity_curve = op_equity_curve(params),
    sma = op_sma(params),
    ema = op_ema(params),
    rsi = op_rsi(params),
    macd = op_macd(params),
    bollinger = op_bollinger(params),
    vwap = op_vwap(params),
    atr = op_atr(params),
    dcf = op_dcf(params),
    multiples = op_multiples(params),
    portfolio_stats = op_portfolio_stats(params),
    beta_alpha = op_beta_alpha(params),
    correlation = op_correlation(params),
    regression = op_regression(params),
    stop(sprintf("unknown op: %s", op))
  )
}

read_params <- function(raw) {
  if (is.null(raw)) return(list())
  if (is.character(raw) && length(raw) == 1 && nzchar(raw)) {
    return(fromJSON(raw, simplifyVector = TRUE))
  }
  raw
}

stdin_con <- file("stdin", open = "r", blocking = TRUE)
repeat {
  line <- tryCatch(readLines(stdin_con, n = 1), error = function(e) character(0))
  if (length(line) == 0) break
  if (!nzchar(line)) next
  req <- tryCatch(fromJSON(line, simplifyVector = FALSE), error = function(e) NULL)
  if (is.null(req)) next
  id <- req$id %||% NA
  op <- req$op %||% ""
  response <- tryCatch(
    {
      result <- dispatch(op, read_params(req$params))
      list(id = id, ok = TRUE, result = sanitize(result))
    },
    error = function(e) list(id = id, ok = FALSE, error = conditionMessage(e))
  )
  cat(toJSON(response, auto_unbox = TRUE, null = "null", na = "null", digits = 10), "\n", sep = "")
  flush(stdout())
  if (identical(op, "shutdown")) break
}
