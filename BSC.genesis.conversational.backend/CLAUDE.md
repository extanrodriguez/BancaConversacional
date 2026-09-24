# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# Build
dotnet build

# Run the API (available at http://localhost:5000)
dotnet run --project src/GenesisBackend.Api/GenesisBackend.Api.csproj

# Run all tests
dotnet test

# Run a single test project
dotnet test tests/GenesisBackend.UnitTests/GenesisBackend.UnitTests.csproj
dotnet test tests/GenesisBackend.IntegrationTests/GenesisBackend.IntegrationTests.csproj

# Run a specific test by name
dotnet test --filter "FullyQualifiedName~HealthEndpointTests"
```

## Architecture

This is a .NET 8 modular monolith with a strict dependency direction:

```
SharedKernel ← Domain ← Application ← Infrastructure
                                    ↖ Api
```

- **SharedKernel** — cross-cutting types, no project dependencies
- **Domain** — pure domain entities and value objects, no infrastructure concerns
- **Application** — use cases, DTOs, service handlers; registers via `AddApplicationServices()` in `ServiceCollectionExtensions`
- **Infrastructure** — persistence and external integrations; registers via `AddInfrastructureServices()` in `ServiceCollectionExtensions`
- **Api** — ASP.NET Core host, controllers, and endpoint mapping; references Application and Infrastructure but not Domain directly

**Modules** (`src/Modules/`) are self-contained feature units each with their own `Domain/` subfolder. They reference SharedKernel. New modules should follow the Conversations and Users examples and be wired into the Api host separately.

### Service registration

All DI wiring goes through [ServiceCollectionExtensions.cs](src/GenesisBackend.Api/Extensions/ServiceCollectionExtensions.cs). Add Application-layer registrations in `AddApplicationServices` and Infrastructure registrations in `AddInfrastructureServices`.

## External auth microservice

Authentication (standard accounts + FIDO2 passkeys) is delegated to an external microservice running at `http://localhost:5252`. This backend calls it as an HTTP dependency — it does **not** implement its own auth logic. The `IAuthClient` (or equivalent typed client) belongs in **Infrastructure** and is registered in `AddInfrastructureServices`.

### Standard account flow

| Method | Endpoint | Body | Response |
|--------|----------|------|----------|
| `POST` | `/auth/register` | `{email, password}` | `201 {id, email, createdAt}` |
| `POST` | `/auth/login` | `{email, password}` | `{accessToken, refreshToken}` |
| `GET`  | `/auth/users` | — | array of users |

### FIDO2 passkey registration

Requires an existing account. Steps must run **in order** — challenges expire after **5 minutes**.

| Method | Endpoint | Body | Response |
|--------|----------|------|----------|
| `POST` | `/fido2/register/options` | `{email}` | WebAuthn `CredentialCreateOptions` |
| `POST` | `/fido2/register/complete` | `{email, attestationResponse}` | `{credentialId}` |

### FIDO2 passkey authentication

| Method | Endpoint | Body | Response |
|--------|----------|------|----------|
| `POST` | `/fido2/authenticate/options` | `{email}` | WebAuthn `AssertionOptions` |
| `POST` | `/oauth/token` | `{email, assertionResponse}` | `{accessToken, refreshToken}` |

The challenge-response state is managed entirely by the auth microservice; this backend acts as a stateless proxy for the passkey flows.

When `Fido2:RpId` is set in [appsettings.json](src/GenesisBackend.Api/appsettings.json), it is injected into the `/fido2/register/options` and `/fido2/authenticate/options` calls so the auth microservice can use the correct domain. When null it is omitted.

## Passkey dev setup (HTTPS required)

Android and iOS both enforce HTTPS at the OS level for passkey flows. Password login works fine on plain HTTP. To test passkeys locally:

**Step 1 — Start an HTTPS tunnel**

```powershell
winget install ngrok   # one-time
ngrok http 5000
# Copy the https://xxxx.ngrok-free.app URL
```

**Step 2 — Set `Fido2:RpId` in `appsettings.Development.json`**

```json
"Fido2": {
  "RpId": "xxxx.ngrok-free.app"
}
```

The subdomain only — no `https://` prefix, no path.

**Step 3 — Configure the auth microservice (`localhost:5252`)**

Set its `rpId` / origin config to the same ngrok domain. The OS verifies that the `rpId` in the WebAuthn response matches the domain the credential was created for; mismatches cause silent failures.

**Step 4 — Fill in `WellKnown` platform values**

*Android SHA-256 fingerprint* (debug keystore):
```bash
keytool -list -v -keystore ~/.android/debug.keystore \
  -alias androiddebugkey -storepass android -keypass android \
  | grep "SHA256:"
```

*iOS App ID*: Xcode → target → Signing & Capabilities → Team ID + Bundle Identifier → combine as `TEAMID.com.yourcompany.app`.

Update `WellKnown:Android:PackageName`, `WellKnown:Android:Sha256CertFingerprints`, and `WellKnown:Ios:AppIds` in appsettings. The backend logs a warning at startup if these still contain placeholder values.

**Step 5 — Point the mobile app at the ngrok URL**

Update `BASE_URL` in the mobile app to the `https://xxxx.ngrok-free.app` tunnel. The ngrok subdomain rotates each restart unless you use a reserved domain (paid plan).

## CI pipelines

Both pipelines live under [.azuredevops/build/](.azuredevops/build/) and target the same branch set: `develop`, `test`, `staging`, `main`.

- **[build.yml](.azuredevops/build/build.yml)** — triggers on push and PR; restores, builds in `Release`, runs both test projects with XPlat Code Coverage collection, and publishes test results.
- **[commit-lint.yml](.azuredevops/build/commit-lint.yml)** — validates conventional commit messages on PRs using `commitlint.config.js`. Allowed types: `feat fix docs style refactor test chore perf ci build revert`. Subject must be non-empty, max header length 100.

### Integration tests

Integration tests use `WebApplicationFactory<GenesisBackend.Api.Program>` (`Microsoft.AspNetCore.Mvc.Testing`). The `Program` partial class lives in [ApiProgram.cs](src/GenesisBackend.Api/ApiProgram.cs) under the `GenesisBackend.Api` namespace — kept separate from [Program.cs](src/GenesisBackend.Api/Program.cs) because top-level statements cannot coexist with a file-scoped namespace declaration. The integration test project already has a `ProjectReference` to `GenesisBackend.Api`.
