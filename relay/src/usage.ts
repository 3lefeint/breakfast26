// What the relay uses of the free plan of Cloudflare, for the admin page: the GraphQL Analytics API answers for Workers (requests,
// errors, CPU time), D1 (queries, rows read and written, size) and R2 (operations of the month by class, storage). The API needs a
// token with "Account > Account Analytics > Read" (Worker secret ANALYTICS_API_TOKEN) and the account id (secret CF_ACCOUNT_ID).
// Every figure is asked on its own, so a dataset or field the API does not know shows its error and leaves the others alone.
// The names of the datasets and fields are those of the documentation of Cloudflare; the unit of the CPU time quantiles is not
// stated there, so the page shows them as they come.

export interface UsageEnv {
  ANALYTICS_API_TOKEN?: string;
  CF_ACCOUNT_ID?: string;
  CF_SCRIPT_NAME?: string;        // default breakfast-relay
  CF_D1_DATABASE_ID?: string;     // without it every D1 database of the account is counted
  CF_R2_BUCKET?: string;          // default breakfast-records
}

export const GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql";

/** The limits of the free plan (checked 2026-10-23 against the pricing and limits pages of Cloudflare). */
export const FREE_LIMITS = {
  workers_requests_day: 100_000,
  d1_rows_read_day: 5_000_000,
  d1_rows_written_day: 100_000,
  d1_database_bytes: 500_000_000,
  r2_storage_bytes: 10_000_000_000,
  r2_class_a_month: 1_000_000,
  r2_class_b_month: 10_000_000,
};

const CLASS_A = ["ListBuckets", "PutBucket", "ListObjects", "PutObject", "CopyObject", "CompleteMultipartUpload", "CreateMultipartUpload",
  "LifecycleStorageTierTransition", "ListMultipartUploads", "UploadPart", "UploadPartCopy", "ListParts", "PutBucketEncryption", "PutBucketCors",
  "PutBucketLifecycleConfiguration"];
const CLASS_B = ["HeadBucket", "HeadObject", "GetObject", "UsageSummary", "GetBucketEncryption", "GetBucketLocation", "GetBucketCors",
  "GetBucketLifecycleConfiguration"];
const FREE_OPERATIONS = ["DeleteObject", "DeleteBucket", "AbortMultipartUpload"];

export type Fetcher = (url: string, init: RequestInit) => Promise<Response>;
export type Part<T> = { data: T } | { error: string };

async function ask(env: UsageEnv, fetcher: Fetcher, query: string, variables: Record<string, unknown>): Promise<any> {
  const res = await fetcher(GRAPHQL_URL, {
    method: "POST",
    headers: { authorization: `Bearer ${env.ANALYTICS_API_TOKEN}`, "content-type": "application/json" },
    body: JSON.stringify({ query, variables: { accountTag: env.CF_ACCOUNT_ID, ...variables } }),
  });
  if (!res.ok) throw new Error(`Cloudflare answered ${res.status}`);
  const body = (await res.json()) as { data?: { viewer?: { accounts?: any[] } }; errors?: { message?: string }[] | null };
  if (body.errors?.length) throw new Error(String(body.errors[0].message ?? "the API reported an error").slice(0, 200));
  return body.data?.viewer?.accounts?.[0] ?? {};
}

async function part<T>(work: () => Promise<T>): Promise<Part<T>> {
  try {
    return { data: await work() };
  } catch (e) {
    return { error: e instanceof Error ? e.message : String(e) };
  }
}

const sum = (rows: any[], pick: (row: any) => unknown) => rows.reduce((total, row) => total + (Number(pick(row)) || 0), 0);
const day = (ms: number) => new Date(ms).toISOString().slice(0, 10);
const iso = (ms: number) => new Date(ms).toISOString();

export async function readUsage(env: UsageEnv, now: number, fetcher: Fetcher = fetch) {
  if (!env.ANALYTICS_API_TOKEN || !env.CF_ACCOUNT_ID) return { configured: false, limits: FREE_LIMITS };
  const script = env.CF_SCRIPT_NAME || "breakfast-relay";
  const bucket = env.CF_R2_BUCKET || "breakfast-records";
  const dayStart = Date.UTC(new Date(now).getUTCFullYear(), new Date(now).getUTCMonth(), new Date(now).getUTCDate());
  const monthStart = Date.UTC(new Date(now).getUTCFullYear(), new Date(now).getUTCMonth(), 1);
  const database = env.CF_D1_DATABASE_ID ? ", databaseId: $databaseId" : "";
  const databaseVariable = env.CF_D1_DATABASE_ID ? ", $databaseId: string" : "";
  const databaseValue = env.CF_D1_DATABASE_ID ? { databaseId: env.CF_D1_DATABASE_ID } : {};

  const [workers, d1, d1Size, r2Operations, r2Storage] = await Promise.all([
    part(async () => {
      const account = await ask(env, fetcher,
        `query ($accountTag: string!, $start: Time, $end: Time, $script: string) { viewer { accounts(filter: { accountTag: $accountTag }) {
           workersInvocationsAdaptive(limit: 100, filter: { scriptName: $script, datetime_geq: $start, datetime_leq: $end }) {
             sum { requests errors subrequests } quantiles { cpuTimeP50 cpuTimeP99 } } } } }`,
        { start: iso(dayStart), end: iso(now), script });
      const rows: any[] = account.workersInvocationsAdaptive ?? [];
      return {
        requests: sum(rows, (r) => r.sum?.requests), errors: sum(rows, (r) => r.sum?.errors), subrequests: sum(rows, (r) => r.sum?.subrequests),
        cpu_p50: Math.max(0, ...rows.map((r) => Number(r.quantiles?.cpuTimeP50) || 0)), cpu_p99: Math.max(0, ...rows.map((r) => Number(r.quantiles?.cpuTimeP99) || 0)),
      };
    }),
    part(async () => {
      const account = await ask(env, fetcher,
        `query ($accountTag: string!, $start: Date, $end: Date${databaseVariable}) { viewer { accounts(filter: { accountTag: $accountTag }) {
           d1AnalyticsAdaptiveGroups(limit: 10000, filter: { date_geq: $start, date_leq: $end${database} }) {
             sum { readQueries writeQueries rowsRead rowsWritten } } } } }`,
        { start: day(now), end: day(now), ...databaseValue });
      const rows: any[] = account.d1AnalyticsAdaptiveGroups ?? [];
      return { read_queries: sum(rows, (r) => r.sum?.readQueries), write_queries: sum(rows, (r) => r.sum?.writeQueries),
        rows_read: sum(rows, (r) => r.sum?.rowsRead), rows_written: sum(rows, (r) => r.sum?.rowsWritten) };
    }),
    part(async () => {
      const account = await ask(env, fetcher,
        `query ($accountTag: string!, $start: Date, $end: Date${databaseVariable}) { viewer { accounts(filter: { accountTag: $accountTag }) {
           d1StorageAdaptiveGroups(limit: 100, filter: { date_geq: $start, date_leq: $end${database} }, orderBy: [date_DESC]) {
             max { databaseSizeBytes } dimensions { date databaseId } } } } }`,
        { start: day(now - 86_400_000), end: day(now), ...databaseValue });
      const rows: any[] = account.d1StorageAdaptiveGroups ?? [];
      const newest = rows.length ? rows[0].dimensions?.date : null;
      return { bytes: sum(rows.filter((r) => r.dimensions?.date === newest), (r) => r.max?.databaseSizeBytes) };
    }),
    part(async () => {
      const account = await ask(env, fetcher,
        `query ($accountTag: string!, $start: Time, $end: Time, $bucket: string) { viewer { accounts(filter: { accountTag: $accountTag }) {
           r2OperationsAdaptiveGroups(limit: 10000, filter: { datetime_geq: $start, datetime_leq: $end, bucketName: $bucket }) {
             sum { requests } dimensions { actionType } } } } }`,
        { start: iso(monthStart), end: iso(now), bucket });
      const rows: any[] = account.r2OperationsAdaptiveGroups ?? [];
      const byAction: Record<string, number> = {};
      for (const r of rows) byAction[r.dimensions?.actionType ?? "unknown"] = (byAction[r.dimensions?.actionType ?? "unknown"] ?? 0) + (Number(r.sum?.requests) || 0);
      const total = (names: string[]) => names.reduce((n, a) => n + (byAction[a] ?? 0), 0);
      const other = Object.entries(byAction).filter(([a]) => ![...CLASS_A, ...CLASS_B, ...FREE_OPERATIONS].includes(a)).reduce((n, [, v]) => n + v, 0);
      return { class_a: total(CLASS_A), class_b: total(CLASS_B), free: total(FREE_OPERATIONS), other, by_action: byAction };
    }),
    part(async () => {
      const account = await ask(env, fetcher,
        `query ($accountTag: string!, $start: Time, $end: Time, $bucket: string) { viewer { accounts(filter: { accountTag: $accountTag }) {
           r2StorageAdaptiveGroups(limit: 1, filter: { datetime_geq: $start, datetime_leq: $end, bucketName: $bucket }, orderBy: [datetime_DESC]) {
             max { objectCount payloadSize metadataSize } dimensions { datetime } } } } }`,
        { start: iso(now - 2 * 86_400_000), end: iso(now), bucket });
      const row = (account.r2StorageAdaptiveGroups ?? [])[0];
      return { bytes: (Number(row?.max?.payloadSize) || 0) + (Number(row?.max?.metadataSize) || 0), objects: Number(row?.max?.objectCount) || 0 };
    }),
  ]);
  return { configured: true, generated_at: now, day: day(now), month: day(monthStart), limits: FREE_LIMITS,
    workers, d1, d1_size: d1Size, r2_operations: r2Operations, r2_storage: r2Storage };
}
