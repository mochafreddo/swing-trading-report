import "server-only";

import { z } from "zod";

const optionalString = z.preprocess((value) => {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}, z.string().optional());

const supabaseSchema = z
  .object({
    SUPABASE_URL: z.string().trim().url(),
    SUPABASE_SECRET_KEY: optionalString,
    SUPABASE_SERVICE_ROLE_KEY: optionalString,
    SUPABASE_REPORTS_BUCKET: optionalString,
    REPORT_RETENTION_DAYS: optionalString
  })
  .superRefine((value, ctx) => {
    if (!value.SUPABASE_SECRET_KEY && !value.SUPABASE_SERVICE_ROLE_KEY) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["SUPABASE_SECRET_KEY"],
        message:
          "Either SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY is required"
      });
    }
  });

const githubSchema = z.object({
  GITHUB_OWNER: z.string().trim().min(1),
  GITHUB_REPO: z.string().trim().min(1),
  GITHUB_PAT: z.string().trim().min(1)
});

export interface SupabaseEnv {
  SUPABASE_URL: string;
  SUPABASE_API_KEY: string;
  SUPABASE_REPORTS_BUCKET: string;
  REPORT_RETENTION_DAYS: number;
}

export interface GitHubEnv {
  GITHUB_OWNER: string;
  GITHUB_REPO: string;
  GITHUB_PAT: string;
}

let cachedSupabaseEnv: SupabaseEnv | null = null;
let cachedGitHubEnv: GitHubEnv | null = null;

export function getSupabaseEnv(): SupabaseEnv {
  if (cachedSupabaseEnv) {
    return cachedSupabaseEnv;
  }

  const parsed = supabaseSchema.parse(process.env);
  const apiKey = parsed.SUPABASE_SECRET_KEY ?? parsed.SUPABASE_SERVICE_ROLE_KEY ?? "";

  if (apiKey.startsWith("sb_publishable_")) {
    throw new Error(
      "SUPABASE publishable key is not allowed for server-side API routes"
    );
  }

  const retention = Number.parseInt(parsed.REPORT_RETENTION_DAYS ?? "30", 10);
  cachedSupabaseEnv = {
    SUPABASE_URL: parsed.SUPABASE_URL.replace(/\/$/, ""),
    SUPABASE_API_KEY: apiKey,
    SUPABASE_REPORTS_BUCKET: parsed.SUPABASE_REPORTS_BUCKET ?? "reports",
    REPORT_RETENTION_DAYS:
      Number.isFinite(retention) && retention > 0 ? retention : 30
  };

  return cachedSupabaseEnv;
}

export function getGitHubEnv(): GitHubEnv {
  if (cachedGitHubEnv) {
    return cachedGitHubEnv;
  }

  const parsed = githubSchema.parse(process.env);
  cachedGitHubEnv = {
    GITHUB_OWNER: parsed.GITHUB_OWNER,
    GITHUB_REPO: parsed.GITHUB_REPO,
    GITHUB_PAT: parsed.GITHUB_PAT
  };
  return cachedGitHubEnv;
}
