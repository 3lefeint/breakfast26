// Ports index.html/tv.html's getCheckout() — identical on both today, now
// shared instead of duplicated.
export function getCheckout(n) {
  if (n > 170 || n < 2) return null;
  const T = {};
  for (let i = 1; i <= 20; i++) T[i] = `S${i}`;
  T[25] = '25';
  for (let i = 7; i <= 20; i++) T[i * 3] = `T${i}`;
  const F = [
    [40, 'D20'], [50, 'Bull'], [32, 'D16'], [36, 'D18'], [38, 'D19'], [34, 'D17'],
    [28, 'D14'], [24, 'D12'], [20, 'D10'], [30, 'D15'], [26, 'D13'], [22, 'D11'],
    [18, 'D9'], [16, 'D8'], [14, 'D7'], [12, 'D6'], [10, 'D5'], [8, 'D4'], [6, 'D3'], [4, 'D2'], [2, 'D1'],
  ];
  for (const [fv, fs] of F) if (n === fv) return [fs];
  for (const [fv, fs] of F) { const need = n - fv; if (need > 0 && T[need]) return [T[need], fs]; }
  const seen = new Set(), first = [];
  for (let i = 20; i >= 1; i--) { const v = i * 3; if (T[v] && !seen.has(v)) { first.push(v); seen.add(v); } }
  [25, ...Array.from({ length: 20 }, (_, k) => 20 - k)].forEach((v) => {
    if (T[v] && !seen.has(v)) { first.push(v); seen.add(v); }
  });
  for (const [fv, fs] of F) {
    const rem2 = n - fv;
    if (rem2 <= 0) continue;
    for (const v1 of first) {
      if (v1 >= rem2 || !T[v1]) continue;
      const v2 = rem2 - v1;
      if (T[v2]) return [T[v1], T[v2], fs];
    }
  }
  return null;
}
