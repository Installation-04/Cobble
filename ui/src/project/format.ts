/** USD amount (the API sends decimals as strings) in the given language. */
export function formatCost(value: string | number, lang: string): string {
  const amount = typeof value === "number" ? value : Number.parseFloat(value);
  return new Intl.NumberFormat(lang, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(Number.isFinite(amount) ? amount : 0);
}

export function formatTokens(value: number, lang: string): string {
  return new Intl.NumberFormat(lang).format(value);
}
