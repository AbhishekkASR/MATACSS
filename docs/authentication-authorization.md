# Authentication and authorization

MATACSS uses a minimal JWT bearer authentication layer for secure access to protected assessment and submission APIs.

## Responsibilities

- `User` stores the authenticated identity, password hash, role, and active flag.
- `UserRole` supports `candidate`, `interviewer`, and `admin`.
- `create_access_token()` issues a signed token backed by `MATACSS_JWT_SECRET`.
- `get_current_active_user()` validates bearer tokens and rejects inactive accounts.
- Route-level authorization checks ensure role-aware access to sensitive resources.

## Security boundaries

- Passwords are never stored in plaintext.
- Only password hashes are persisted.
- JWT secrets are read from environment configuration and are never hard-coded.
- Token validation rejects malformed, expired, or mismatched-role tokens.
- Candidate access is constrained to the candidate's own interview and submission records.
- Interviewer and admin roles are allowed to manage assessment and evaluation data.

## Protected resources

Protected routes require an authenticated user when `MATACSS_JWT_SECRET` is configured.

- candidate resource creation is restricted to interviewer/admin users
- interview lifecycle endpoints require valid access for the owning candidate or authorized staff
- question and test-case creation are limited to interviewer/admin
- submission endpoints are restricted to the owning candidate or authorized staff
- evaluation and result endpoints follow the same ownership checks

## Legacy compatibility

When no JWT secret is configured, the application keeps the existing non-authenticated local-development behavior. This preserves compatibility with the local test and dev flow while still providing strict validation when auth is enabled.

## Future work

This foundation provides the core application auth and role checks. It does not add OAuth providers, multi-tenant identity integrations, or automated permission policies beyond the allowed local platform roles.
