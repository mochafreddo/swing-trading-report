create or replace function public.holdings_add_buy_v1(
  p_ticker text,
  p_buy_quantity numeric,
  p_buy_price numeric,
  p_buy_date date default null
)
returns setof public.holdings
language plpgsql
as $$
declare
  v_ticker_key text := trim(coalesce(p_ticker, ''));
  v_target public.holdings%rowtype;
  v_required_currency text;
  v_currency text;
  v_new_quantity numeric(20, 6);
  v_new_entry_price numeric(20, 4);
  v_new_entry_date date;
begin
  if v_ticker_key = '' then
    raise exception 'ticker is required';
  end if;

  if p_buy_quantity is null or p_buy_quantity <= 0 then
    raise exception 'buy_quantity must be > 0';
  end if;

  if p_buy_price is null or p_buy_price <= 0 then
    raise exception 'buy_price must be > 0';
  end if;

  select *
  into v_target
  from public.holdings
  where public.canonical_holdings_ticker(ticker) =
    public.canonical_holdings_ticker(v_ticker_key)
  limit 1
  for update;

  if not found then
    return;
  end if;

  v_required_currency := case
    when v_target.ticker ~ '^\d{6}$' then 'KRW'
    else 'USD'
  end;

  v_currency := upper(trim(coalesce(v_target.entry_currency, '')));
  if v_currency = '' then
    v_currency := v_required_currency;
  elsif v_currency <> v_required_currency then
    raise exception
      'entry_currency mismatch for ticker %: expected %, got %',
      v_target.ticker,
      v_required_currency,
      v_currency;
  end if;

  if v_target.quantity > 0 and coalesce(v_target.entry_price, 0) <= 0 then
    raise exception
      'existing holding has non-positive entry_price for positive quantity (ticker %)',
      v_target.ticker;
  end if;

  v_new_quantity := round((coalesce(v_target.quantity, 0)::numeric + p_buy_quantity), 6);
  if v_new_quantity <= 0 then
    raise exception 'resulting quantity must be > 0';
  end if;

  if coalesce(v_target.quantity, 0) = 0 then
    v_new_entry_price := round(p_buy_price, 4);
  else
    v_new_entry_price := round(
      (
        (v_target.quantity::numeric * v_target.entry_price::numeric)
        + (p_buy_quantity * p_buy_price)
      ) / v_new_quantity,
      4
    );
  end if;

  v_new_entry_date := v_target.entry_date;
  if p_buy_date is not null and (v_new_entry_date is null or p_buy_date < v_new_entry_date) then
    v_new_entry_date := p_buy_date;
  end if;

  update public.holdings
  set quantity = v_new_quantity,
      entry_price = v_new_entry_price,
      entry_currency = v_currency,
      entry_date = v_new_entry_date
  where ticker = v_target.ticker;

  return query
  select *
  from public.holdings
  where ticker = v_target.ticker;
end;
$$;

revoke all on function public.holdings_add_buy_v1(
  text,
  numeric,
  numeric,
  date
) from anon;

revoke all on function public.holdings_add_buy_v1(
  text,
  numeric,
  numeric,
  date
) from authenticated;
