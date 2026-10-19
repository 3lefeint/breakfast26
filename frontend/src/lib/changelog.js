// The changes of one version from the changelog of the app, null when there is no entry for it.
export async function changesOf(version) {
  try {
    const res = await fetch('/api/changelog').then((r) => r.json());
    return (res.versions ?? []).find((v) => v.version === version) ?? null;
  } catch (_) {
    return null;
  }
}
