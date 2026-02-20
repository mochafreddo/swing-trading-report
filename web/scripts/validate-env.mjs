function requireNonEmpty(name) {
  const raw = process.env[name];
  const value = typeof raw === "string" ? raw.trim() : "";
  if (!value) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

function requireAnyNonEmpty(names) {
  for (const name of names) {
    const raw = process.env[name];
    const value = typeof raw === "string" ? raw.trim() : "";
    if (value) {
      return value;
    }
  }
  throw new Error(`Missing required env var: one of ${names.join(", ")}`);
}

function requireMinLength(name, minLength) {
  const value = requireNonEmpty(name);
  if (value.length < minLength) {
    throw new Error(
      `Missing required env var: ${name} must be at least ${minLength} chars`,
    );
  }
  return value;
}

if (process.env.NODE_ENV !== "test") {
  requireNonEmpty("SAB_BASIC_AUTH_USER");
  requireNonEmpty("SAB_BASIC_AUTH_PASS");
  requireMinLength("SAB_SESSION_SECRET", 32);

  requireNonEmpty("SUPABASE_URL");
  requireAnyNonEmpty(["SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"]);

  requireNonEmpty("GITHUB_OWNER");
  requireNonEmpty("GITHUB_REPO");
  requireNonEmpty("GITHUB_PAT");
}
