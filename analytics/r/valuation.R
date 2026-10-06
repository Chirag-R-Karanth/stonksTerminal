num_param <- function(params, key) {
  v <- suppressWarnings(as.numeric(unlist(params[[key]]))[1])
  if (is.finite(v)) v else NA_real_
}

op_multiples <- function(params) {
  price <- num_param(params, "price")
  shares <- num_param(params, "shares")
  market_cap <- num_param(params, "market_cap")
  if (!is.finite(market_cap) && is.finite(price) && is.finite(shares)) {
    market_cap <- price * shares
  }
  net_income <- num_param(params, "net_income")
  revenue <- num_param(params, "revenue")
  gross_profit <- num_param(params, "gross_profit")
  operating_income <- num_param(params, "operating_income")
  ebitda <- num_param(params, "ebitda")
  book_equity <- num_param(params, "shareholders_equity")
  total_debt <- num_param(params, "total_debt")
  cash <- num_param(params, "cash")
  fcf <- num_param(params, "free_cash_flow")
  ebit <- num_param(params, "ebit")
  dps <- num_param(params, "dividend_per_share")
  tax_rate <- num_param(params, "tax_rate")
  if (!is.finite(tax_rate)) tax_rate <- 0.21

  debt <- if (is.finite(total_debt)) total_debt else 0
  cash_v <- if (is.finite(cash)) cash else 0
  ev <- if (is.finite(market_cap)) market_cap + debt - cash_v else NA_real_
  eps <- if (is.finite(net_income) && is.finite(shares) && shares > 0) net_income / shares else NA_real_
  pe <- if (is.finite(price) && is.finite(eps) && eps > 0) price / eps else NA_real_
  ps <- if (is.finite(market_cap) && is.finite(revenue) && revenue > 0) market_cap / revenue else NA_real_
  pb <- if (is.finite(market_cap) && is.finite(book_equity) && book_equity > 0) market_cap / book_equity else NA_real_
  ev_ebitda <- if (is.finite(ev) && is.finite(ebitda) && ebitda > 0) ev / ebitda else NA_real_
  ev_sales <- if (is.finite(ev) && is.finite(revenue) && revenue > 0) ev / revenue else NA_real_
  ev_fcf <- if (is.finite(ev) && is.finite(fcf) && fcf > 0) ev / fcf else NA_real_
  dividend_yield <- if (is.finite(price) && is.finite(dps) && price > 0 && dps >= 0) dps / price else NA_real_
  roe <- if (is.finite(net_income) && is.finite(book_equity) && book_equity > 0) net_income / book_equity else NA_real_
  invested_capital <- if (is.finite(book_equity)) book_equity + debt - cash_v else NA_real_
  nopat <- if (is.finite(ebit)) ebit * (1 - tax_rate) else NA_real_
  roic <- if (is.finite(nopat) && is.finite(invested_capital) && invested_capital > 0) nopat / invested_capital else NA_real_
  gross_margin <- if (is.finite(gross_profit) && is.finite(revenue) && revenue > 0) gross_profit / revenue else NA_real_
  operating_margin <- if (is.finite(operating_income) && is.finite(revenue) && revenue > 0) operating_income / revenue else NA_real_
  net_margin <- if (is.finite(net_income) && is.finite(revenue) && revenue > 0) net_income / revenue else NA_real_
  fcf_margin <- if (is.finite(fcf) && is.finite(revenue) && revenue > 0) fcf / revenue else NA_real_
  debt_to_equity <- if (is.finite(total_debt) && is.finite(book_equity) && book_equity > 0) total_debt / book_equity else NA_real_

  list(
    pe = pe, earnings_per_share = eps, price_to_sales = ps, price_to_book = pb,
    ev_to_ebitda = ev_ebitda, ev_to_sales = ev_sales, ev_to_fcf = ev_fcf,
    dividend_yield = dividend_yield, roe = roe, roic = roic,
    gross_margin = gross_margin, operating_margin = operating_margin,
    net_margin = net_margin, fcf_margin = fcf_margin,
    debt_to_equity = debt_to_equity, market_cap = market_cap,
    enterprise_value = ev, tax_rate_used = tax_rate
  )
}

run_dcf_case <- function(revenue0, shares, growth, ebit_margin, tax, capex_pct, nwc_pct,
                         da_pct, wacc, g_term, years, net_debt) {
  g_vec <- if (length(growth) >= years) growth[1:years] else c(rep(growth[1], years - length(growth)), growth)
  revenue_prev <- revenue0
  nwc_prev <- revenue0 * nwc_pct
  pv_sum <- 0
  projections <- vector("list", years)
  fcf_last <- NA_real_
  for (t in seq_len(years)) {
    gt <- g_vec[t]
    revenue_t <- revenue_prev * (1 + gt)
    ebit_t <- revenue_t * ebit_margin
    nopat_t <- ebit_t * (1 - tax)
    da_t <- revenue_t * da_pct
    capex_t <- revenue_t * capex_pct
    nwc_t <- revenue_t * nwc_pct
    dnwc <- nwc_t - nwc_prev
    fcf_t <- nopat_t + da_t - capex_t - dnwc
    pv_t <- fcf_t / (1 + wacc)^t
    pv_sum <- pv_sum + pv_t
    projections[[t]] <- list(year = t, revenue = revenue_t, ebit = ebit_t, fcf = fcf_t, present_value = pv_t)
    revenue_prev <- revenue_t
    nwc_prev <- nwc_t
    fcf_last <- fcf_t
  }
  terminal_value <- fcf_last * (1 + g_term) / (wacc - g_term)
  pv_terminal <- terminal_value / (1 + wacc)^years
  enterprise_value <- pv_sum + pv_terminal
  equity_value <- enterprise_value - net_debt
  per_share <- if (is.finite(shares) && shares > 0) equity_value / shares else NA_real_
  list(
    enterprise_value = enterprise_value,
    equity_value = equity_value,
    intrinsic_value = per_share,
    terminal_value = terminal_value,
    pv_terminal_share = if (enterprise_value != 0) pv_terminal / enterprise_value else NA_real_,
    projections = projections
  )
}

op_dcf <- function(params) {
  revenue0 <- num_param(params, "revenue")
  shares <- num_param(params, "shares")
  growth <- as.numeric(unlist(params$growth))
  if (!length(growth) || !any(is.finite(growth))) stop("growth assumption required")
  growth <- growth[is.finite(growth)]
  ebit_margin <- num_param(params, "ebit_margin")
  if (!is.finite(ebit_margin)) stop("ebit_margin assumption required")
  tax <- num_param(params, "tax_rate")
  if (!is.finite(tax)) tax <- 0.21
  capex_pct <- num_param(params, "capex_pct")
  if (!is.finite(capex_pct)) capex_pct <- 0.04
  nwc_pct <- num_param(params, "nwc_pct")
  if (!is.finite(nwc_pct)) nwc_pct <- 0.05
  da_pct <- num_param(params, "da_pct")
  if (!is.finite(da_pct)) da_pct <- 0
  wacc <- num_param(params, "wacc")
  if (!is.finite(wacc)) stop("wacc assumption required")
  g_term <- num_param(params, "terminal_growth")
  if (!is.finite(g_term)) g_term <- 0.02
  years <- as.integer(num_param(params, "years"))
  if (!is.finite(years) || years < 1) years <- 10
  net_debt <- num_param(params, "net_debt")
  if (!is.finite(net_debt)) net_debt <- 0
  price <- num_param(params, "price")
  if (wacc <= g_term) stop("wacc must be greater than terminal growth")

  scen <- params$scenarios
  bull_growth_delta <- if (!is.null(scen$bull$growth_delta)) as.numeric(scen$bull$growth_delta)[1] else 0.02
  bull_wacc_delta <- if (!is.null(scen$bull$wacc_delta)) as.numeric(scen$bull$wacc_delta)[1] else -0.01
  bull_margin_delta <- if (!is.null(scen$bull$margin_delta)) as.numeric(scen$bull$margin_delta)[1] else 0.01
  bear_growth_delta <- if (!is.null(scen$bear$growth_delta)) as.numeric(scen$bear$growth_delta)[1] else -0.03
  bear_wacc_delta <- if (!is.null(scen$bear$wacc_delta)) as.numeric(scen$bear$wacc_delta)[1] else 0.015
  bear_margin_delta <- if (!is.null(scen$bear$margin_delta)) as.numeric(scen$bear$margin_delta)[1] else -0.02

  base <- run_dcf_case(revenue0, shares, growth, ebit_margin, tax, capex_pct, nwc_pct,
                       da_pct, wacc, g_term, years, net_debt)
  bull <- run_dcf_case(revenue0, shares, growth + bull_growth_delta, ebit_margin + bull_margin_delta,
                       tax, capex_pct, nwc_pct, da_pct, max(wacc + bull_wacc_delta, g_term + 0.005),
                       g_term, years, net_debt)
  bear <- run_dcf_case(revenue0, shares, growth + bear_growth_delta, ebit_margin + bear_margin_delta,
                       tax, capex_pct, nwc_pct, da_pct, max(wacc + bear_wacc_delta, g_term + 0.005),
                       g_term, years, net_debt)

  upside <- if (is.finite(price) && price > 0 && is.finite(base$intrinsic_value)) {
    base$intrinsic_value / price - 1
  } else NA_real_

  list(
    assumptions = list(
      revenue = revenue0, growth = I(as.numeric(growth)), ebit_margin = ebit_margin,
      tax_rate = tax, capex_pct = capex_pct, nwc_pct = nwc_pct, da_pct = da_pct,
      wacc = wacc, terminal_growth = g_term, years = years, net_debt = net_debt
    ),
    base = base,
    bull = list(intrinsic_value = bull$intrinsic_value, equity_value = bull$equity_value),
    bear = list(intrinsic_value = bear$intrinsic_value, equity_value = bear$equity_value),
    upside_vs_price = upside,
    model = "dcf"
  )
}
